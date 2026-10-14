import base64,hashlib,os
from urllib.parse import urlsplit
from django.conf import settings
from cryptography.fernet import Fernet
import stripe

def cipher():
    key=os.getenv('PAYMENT_ENCRYPTION_KEY') or base64.urlsafe_b64encode(hashlib.sha256(('recitera-payments-v1:'+settings.SECRET_KEY).encode()).digest()).decode()
    return Fernet(key.encode())
def encrypt(value):return cipher().encrypt(value.encode()).decode() if value else ''
def decrypt(value):return cipher().decrypt(value.encode()).decode() if value else ''
def credentials(config,mode=None):
    mode=mode or config.mode
    key=decrypt(getattr(config,f'{mode}_secret_ciphertext')) or os.getenv(f'STRIPE_{mode.upper()}_SECRET_KEY','')
    secret=decrypt(getattr(config,f'{mode}_webhook_ciphertext')) or os.getenv(f'STRIPE_{mode.upper()}_WEBHOOK_SECRET','')
    return key,secret
def ready(config):
    if not config or not config.enabled:return False
    key,secret=credentials(config)
    return key.startswith(f'sk_{config.mode}_') and secret.startswith('whsec_')
def client(config,mode=None):
    key,_=credentials(config,mode)
    return stripe.StripeClient(key,max_network_retries=1,http_client=stripe.RequestsClient(timeout=15))
def valid_origin(value):
    parsed=urlsplit(value)
    return parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password and parsed.path in ['','/'] and not parsed.query and not parsed.fragment
