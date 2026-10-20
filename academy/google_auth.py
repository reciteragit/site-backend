"""Google authorization code + PKCE, browser-bound state and verified OIDC identity."""
import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, IntegrityError
from django.utils import timezone
from google.auth.transport.requests import Request as GoogleRequest
from google.auth import exceptions as google_errors
from google.oauth2 import id_token
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .views import AcademyView, AcademyAuthThrottle, profile_data
from .authentication import issue_token
from .models import GoogleAuthorization, GoogleIdentity, Profile
from .timezones import zone


def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def cipher():
    key=hashlib.sha256(('recitera-google-auth-v1:'+settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))
def safe_next(value):
    return value if isinstance(value,str) and re.fullmatch(r'/(?:account(?:/teaching)?|cart|checkout|teachers/[a-z0-9-]+)',value) else '/account'
def configured(redirect_uri):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or redirect_uri not in settings.GOOGLE_REDIRECT_URIS:return False
    parsed=urlsplit(redirect_uri)
    local=settings.DEBUG and parsed.hostname in ['localhost','127.0.0.1']
    return not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path=='/api/auth/google/callback' and (parsed.scheme=='https' or (local and parsed.scheme=='http'))


class BoundedGoogleRequest(GoogleRequest):
    def __call__(self,*args,**kwargs):
        kwargs['timeout']=8
        return super().__call__(*args,**kwargs)


def exchange_code(code,attempt):
    payload=urlencode({'grant_type':'authorization_code','client_id':settings.GOOGLE_CLIENT_ID,'client_secret':settings.GOOGLE_CLIENT_SECRET,'redirect_uri':attempt.redirect_uri,'code':code,'code_verifier':cipher().decrypt(attempt.verifier_ciphertext.encode()).decode()}).encode()
    request=Request('https://oauth2.googleapis.com/token',data=payload,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urlopen(request,timeout=8) as response:tokens=json.loads(response.read(65536))
    token=tokens.get('id_token')
    if not isinstance(token,str) or len(token)>16000:raise ValueError('Missing identity token')
    claims=id_token.verify_oauth2_token(token,BoundedGoogleRequest(),settings.GOOGLE_CLIENT_ID)
    if claims.get('aud')!=settings.GOOGLE_CLIENT_ID or claims.get('iss') not in ['accounts.google.com','https://accounts.google.com'] or claims.get('azp',settings.GOOGLE_CLIENT_ID)!=settings.GOOGLE_CLIENT_ID:raise ValueError('Invalid token audience or issuer')
    if not isinstance(claims.get('nonce'),str) or not hmac.compare_digest(digest(claims['nonce']),attempt.nonce_digest):raise ValueError('Invalid nonce')
    if claims.get('email_verified') is not True:raise ValueError('Unverified email')
    subject=claims.get('sub');email=claims.get('email')
    if not isinstance(subject,str) or not subject or len(subject)>255 or not isinstance(email,str) or len(email)>150:raise ValueError('Invalid identity')
    email=email.strip().lower();validate_email(email)
    return claims,email


class GoogleConfiguration(AcademyView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request):return Response({'enabled':configured(request.query_params.get('redirect_uri',''))})


class GoogleStart(AcademyView):
    permission_classes=[AllowAny];throttle_classes=[AcademyAuthThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            redirect_uri=serializers.URLField(max_length=500)
            timezone=serializers.CharField(max_length=100,default='UTC')
            next=serializers.CharField(max_length=300,default='/account')
            mode=serializers.ChoiceField(choices=['login','link'],default='login')
        serializer=Input(data=request.data);serializer.is_valid(raise_exception=True);data=serializer.validated_data
        if not configured(data['redirect_uri']):return Response({'error':'Google sign-in is currently unavailable. Please use email.','code':'google_unavailable'},status=503)
        zone(data['timezone'])
        if data['mode']=='link' and not request.user.is_authenticated:return Response({'error':'Sign in before connecting Google.','code':'google_link_signin'},status=401)
        state=secrets.token_urlsafe(32);binding=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        GoogleAuthorization.objects.filter(expires_at__lt=timezone.now()-timedelta(days=1)).delete()
        GoogleAuthorization.objects.create(digest=digest(state),binding_digest=digest(binding),nonce_digest=digest(nonce),verifier_ciphertext=cipher().encrypt(verifier.encode()).decode(),redirect_uri=data['redirect_uri'],next_path=safe_next(data['next']),timezone=data['timezone'],mode=data['mode'],user=request.user if data['mode']=='link' else None,expires_at=timezone.now()+timedelta(minutes=10))
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        url='https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':settings.GOOGLE_CLIENT_ID,'redirect_uri':data['redirect_uri'],'response_type':'code','scope':'openid email profile','state':state,'nonce':nonce,'code_challenge':challenge,'code_challenge_method':'S256','prompt':'select_account'})
        return Response({'authorization_url':url,'state':state,'binding':binding,'mode':data['mode']})


class GoogleComplete(AcademyView):
    permission_classes=[AllowAny];throttle_classes=[AcademyAuthThrottle]
    def post(self,request):
        class Input(serializers.Serializer):
            state=serializers.CharField(max_length=128)
            binding=serializers.CharField(max_length=128)
            code=serializers.CharField(max_length=4096)
            redirect_uri=serializers.URLField(max_length=500)
        serializer=Input(data=request.data);serializer.is_valid(raise_exception=True);data=serializer.validated_data
        if not configured(data['redirect_uri']):return Response({'code':'google_unavailable'},status=503)
        with transaction.atomic():
            attempt=GoogleAuthorization.objects.select_for_update().filter(digest=digest(data['state'])).first()
            if not attempt or attempt.consumed_at or attempt.expires_at<=timezone.now() or attempt.redirect_uri!=data['redirect_uri'] or not hmac.compare_digest(attempt.binding_digest,digest(data['binding'])):return Response({'code':'google_invalid_state'},status=400)
            if attempt.mode=='link' and (not request.user.is_authenticated or request.user.pk!=attempt.user_id):return Response({'code':'google_link_signin'},status=401)
            attempt.consumed_at=timezone.now();attempt.save(update_fields=['consumed_at'])
        try:claims,email=exchange_code(data['code'],attempt)
        except (HTTPError,URLError,OSError,ValueError,InvalidToken,DjangoValidationError,google_errors.GoogleAuthError):return Response({'code':'google_verification_failed'},status=400)
        User=get_user_model()
        try:
            with transaction.atomic():
                identity=GoogleIdentity.objects.select_for_update().select_related('user').filter(subject=claims['sub']).first()
                if attempt.mode=='link':
                    user=User.objects.select_for_update().get(pk=attempt.user_id)
                    if not user.is_active:return Response({'code':'google_account_disabled'},status=403)
                    if (identity and identity.user_id!=user.pk) or GoogleIdentity.objects.filter(user=user).exclude(subject=claims['sub']).exists():return Response({'code':'google_link_conflict'},status=409)
                    if not identity:GoogleIdentity.objects.create(subject=claims['sub'],email=email,user=user)
                elif identity:
                    user=identity.user
                    if not user.is_active:return Response({'code':'google_account_disabled'},status=403)
                else:
                    # Never infer account ownership from matching email alone. Existing
                    # users sign in with password and explicitly connect Google instead.
                    if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():return Response({'code':'google_email_exists'},status=409)
                    first=claims.get('given_name','');last=claims.get('family_name','')
                    user=User.objects.create_user(username=email,email=email,first_name=first[:100] if isinstance(first,str) else '',last_name=last[:100] if isinstance(last,str) else '')
                    user.set_unusable_password();user.save(update_fields=['password'])
                    Profile.objects.create(user=user,timezone=attempt.timezone)
                    GoogleIdentity.objects.create(subject=claims['sub'],email=email,user=user)
                token=issue_token(user)
        except (IntegrityError,User.DoesNotExist):return Response({'code':'google_account_conflict'},status=409)
        return Response({'token':token,'next':attempt.next_path,'linked':attempt.mode=='link','profile':profile_data(user)})
