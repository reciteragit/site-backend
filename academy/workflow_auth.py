"""Verify short-lived GitHub Actions OIDC tokens for the one trusted reminder workflow."""
import base64
import json
import time
from urllib.request import urlopen
from django.core.cache import cache
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

AUDIENCE='recitera-class-reminders'
WORKFLOW='reciteragit/site-backend/.github/workflows/reminders.yml@refs/heads/main'


def workflow_authorized(token):
    try:
        if len(token)>20000:return False
        def decode(value):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))
        header,body,signature=token.split('.')
        metadata=json.loads(decode(header));claims=json.loads(decode(body))
        if metadata.get('alg')!='RS256' or not isinstance(metadata.get('kid'),str):return False
        now=time.time()
        if claims.get('iss')!='https://token.actions.githubusercontent.com' or claims.get('aud')!=AUDIENCE:return False
        if claims.get('repository')!='reciteragit/site-backend' or claims.get('ref')!='refs/heads/main':return False
        if claims.get('workflow_ref')!=WORKFLOW or claims.get('job_workflow_ref',WORKFLOW)!=WORKFLOW or claims.get('event_name') not in ['schedule','workflow_dispatch']:return False
        if claims.get('sub')!='repo:reciteragit/site-backend:ref:refs/heads/main':return False
        if not now-30<claims['exp']<=now+900 or claims['iat']>now+30 or claims['iat']<now-900 or claims.get('nbf',0)>now+30:return False
        keys=cache.get('recitera-github-oidc-jwks')
        if not keys or not any(key.get('kid')==metadata['kid'] for key in keys):
            with urlopen('https://token.actions.githubusercontent.com/.well-known/jwks',timeout=8) as response:
                keys=json.loads(response.read(65536))['keys']
            cache.set('recitera-github-oidc-jwks',keys,300)
        key=next(key for key in keys if key.get('kid')==metadata['kid'] and key.get('kty')=='RSA')
        numbers=rsa.RSAPublicNumbers(int.from_bytes(decode(key['e']),'big'),int.from_bytes(decode(key['n']),'big'))
        numbers.public_key().verify(decode(signature),(header+'.'+body).encode(),padding.PKCS1v15(),hashes.SHA256())
        return True
    except Exception:
        return False
