import base64
import hashlib
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch,MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes,serialization
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase,override_settings
from django.utils import timezone
from django.core.cache import cache
from rest_framework.test import APIClient
from .models import GoogleAuthorization,GoogleIdentity,Profile,AccessToken
from .authentication import issue_token
from .google_auth import cipher

REDIRECT='https://www.recitera.com/api/auth/google/callback'
User=get_user_model()

def b64(value):return base64.urlsafe_b64encode(value).decode().rstrip('=')

@override_settings(GOOGLE_CLIENT_ID='google-client.apps.googleusercontent.com',GOOGLE_CLIENT_SECRET='google-secret-fixture',GOOGLE_REDIRECT_URIS=[REDIRECT])
class GoogleAuthTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.public=cls.private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    def setUp(self):cache.clear();self.api=APIClient()
    def start(self,**updates):
        data={'redirect_uri':REDIRECT,'timezone':'Asia/Tehran','next':'/cart','mode':'login'};data.update(updates)
        response=self.api.post('/api/academy/auth/google/start/',data,format='json')
        self.assertEqual(response.status_code,200,response.data);return response.data
    def claims(self,flow,**overrides):
        nonce=parse_qs(urlsplit(flow['authorization_url']).query)['nonce'][0]
        data={'iss':'https://accounts.google.com','aud':settings.GOOGLE_CLIENT_ID,'azp':settings.GOOGLE_CLIENT_ID,'sub':'google_subject_fixture','email':'new-google@example.com','email_verified':True,'given_name':'Google','family_name':'Learner','nonce':nonce,'iat':int(time.time())-5,'exp':int(time.time())+600};data.update(overrides);return data
    def token(self,claims):
        head=b64(json.dumps({'alg':'RS256','kid':'fixture_key','typ':'JWT'}).encode());payload=b64(json.dumps(claims).encode());raw=(head+'.'+payload).encode()
        return head+'.'+payload+'.'+b64(self.private.sign(raw,padding.PKCS1v15(),hashes.SHA256()))
    def complete(self,flow,claims=None,**overrides):
        claims=claims or self.claims(flow)
        data={'state':flow['state'],'binding':flow['binding'],'code':'code-fixture','redirect_uri':REDIRECT};data.update(overrides)
        with patch('academy.google_auth.urlopen') as exchange,patch('academy.google_auth.BoundedGoogleRequest') as transport:
            response=MagicMock();response.read.return_value=json.dumps({'id_token':self.token(claims)}).encode();exchange.return_value.__enter__.return_value=response
            transport.return_value.return_value=SimpleNamespace(status=200,data=json.dumps({'fixture_key':self.public}).encode())
            return self.api.post('/api/academy/auth/google/complete/',data,format='json')
    def test_configuration_disabled_without_secret_and_rejects_unlisted_redirect(self):
        with override_settings(GOOGLE_CLIENT_SECRET=''):
            self.assertFalse(self.api.get('/api/academy/auth/google/config/',{'redirect_uri':REDIRECT}).data['enabled'])
            self.assertEqual(self.api.post('/api/academy/auth/google/start/',{'redirect_uri':REDIRECT},format='json').status_code,503)
        self.assertFalse(self.api.get('/api/academy/auth/google/config/',{'redirect_uri':'https://attacker.test/api/auth/google/callback'}).data['enabled'])
    def test_start_uses_pkce_nonce_minimal_scope_and_encrypted_verifier(self):
        flow=self.start(next='//attacker.test');query=parse_qs(urlsplit(flow['authorization_url']).query)
        self.assertEqual(query['scope'],['openid email profile']);self.assertEqual(query['code_challenge_method'],['S256'])
        attempt=GoogleAuthorization.objects.get();verifier=cipher().decrypt(attempt.verifier_ciphertext.encode()).decode()
        self.assertEqual(query['code_challenge'],[b64(hashlib.sha256(verifier.encode()).digest())])
        self.assertNotEqual(attempt.digest,flow['state']);self.assertNotIn(verifier,flow['authorization_url']);self.assertEqual(attempt.next_path,'/account')
    def test_real_rsa_verified_google_token_creates_passwordless_account_and_session(self):
        flow=self.start();response=self.complete(flow)
        self.assertEqual(response.status_code,200,response.data)
        user=User.objects.get(email='new-google@example.com');self.assertFalse(user.has_usable_password())
        self.assertEqual(Profile.objects.get(user=user).timezone,'Asia/Tehran');self.assertEqual(GoogleIdentity.objects.get().subject,'google_subject_fixture')
        self.assertTrue(response.data['profile']['google_connected']);self.assertFalse(response.data['profile']['has_password'])
        self.assertEqual(response.data['next'],'/cart');self.assertEqual(AccessToken.objects.count(),1)
        self.assertEqual(self.complete(flow).status_code,400)
    def test_wrong_browser_binding_does_not_consume_legitimate_flow(self):
        flow=self.start();self.assertEqual(self.complete(flow,binding='wrong-browser').status_code,400)
        self.assertIsNone(GoogleAuthorization.objects.get().consumed_at)
        self.assertEqual(self.complete(flow).status_code,200)
    def test_expired_state_does_not_create_user(self):
        flow=self.start();GoogleAuthorization.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.complete(flow).status_code,400);self.assertFalse(User.objects.exists())
    def test_invalid_audience_issuer_nonce_email_and_expiry_are_rejected(self):
        for overrides in [{'aud':'other-client'},{'iss':'https://attacker.test'},{'nonce':'wrong'},{'email_verified':False},{'email_verified':'true'},{'exp':int(time.time())-100},{'azp':'other-client'}]:
            with self.subTest(overrides=overrides):
                cache.clear();flow=self.start();response=self.complete(flow,self.claims(flow,**overrides))
                self.assertEqual(response.status_code,400,response.data)
                self.assertEqual(response.data['code'],'google_verification_failed');self.assertFalse(User.objects.exists())
    def test_existing_email_is_never_silently_linked(self):
        User.objects.create_user(username='new-google@example.com',email='NEW-GOOGLE@example.com',password='Existing-password-9!')
        flow=self.start();response=self.complete(flow)
        self.assertEqual(response.status_code,409);self.assertEqual(response.data['code'],'google_email_exists');self.assertFalse(GoogleIdentity.objects.exists());self.assertEqual(User.objects.count(),1)
    def test_signed_in_owner_can_explicitly_link_then_log_in_with_google(self):
        user=User.objects.create_user(username='existing@example.com',email='existing@example.com',password='Existing-password-9!');original=user.password
        self.api.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(user))
        flow=self.start(mode='link',next='/account');response=self.complete(flow)
        self.assertEqual(response.status_code,200,response.data);self.assertTrue(response.data['linked'])
        self.assertEqual(GoogleIdentity.objects.get().user,user)
        self.api.credentials();flow=self.start();response=self.complete(flow)
        self.assertEqual(response.status_code,200,response.data);self.assertEqual(response.data['profile']['id'],user.pk)
        user.refresh_from_db();self.assertEqual(user.password,original);self.assertEqual(User.objects.count(),1)
    def test_link_requires_current_session_and_cannot_reassign_another_google_identity(self):
        self.assertEqual(self.api.post('/api/academy/auth/google/start/',{'redirect_uri':REDIRECT,'mode':'link'},format='json').status_code,401)
        user=User.objects.create_user('owner@example.com',email='owner@example.com');other=User.objects.create_user('other@example.com',email='other@example.com')
        GoogleIdentity.objects.create(subject='google_subject_fixture',user=other,email='new-google@example.com')
        self.api.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(user));flow=self.start(mode='link')
        self.assertEqual(self.complete(flow).data['code'],'google_link_conflict')
        flow=self.start(mode='link');self.api.credentials()
        self.assertEqual(self.complete(flow).status_code,401)
    def test_disabled_linked_account_cannot_sign_in(self):
        user=User.objects.create_user('disabled@example.com',email='disabled@example.com',is_active=False)
        GoogleIdentity.objects.create(user=user,subject='google_subject_fixture',email='new-google@example.com')
        flow=self.start();self.assertEqual(self.complete(flow).status_code,403)
