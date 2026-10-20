import hashlib
import secrets
from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from .models import AccessToken


def issue_token(user):
    raw = secrets.token_urlsafe(48)
    AccessToken.objects.create(user=user, digest=hashlib.sha256(raw.encode()).hexdigest(), expires_at=timezone.now()+timedelta(days=14))
    return raw


class AcademyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header: return None
        if len(header)!=2 or header[0].lower()!=b'bearer': raise AuthenticationFailed('Invalid session.')
        digest = hashlib.sha256(header[1]).hexdigest()
        token = AccessToken.objects.select_related('user').filter(digest=digest, expires_at__gt=timezone.now(), user__is_active=True).first()
        if not token: raise AuthenticationFailed('Your session expired. Please sign in again.')
        return token.user, token
    def authenticate_header(self, request): return 'Bearer'
