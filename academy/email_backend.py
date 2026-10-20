"""Transactional email through Resend's HTTPS API; no SMTP account required."""
import base64
import hashlib
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class ResendDeliveryError(Exception):
    """Safe exception type: never include credentials or message bodies in errors."""


class ResendBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        count = 0
        for message in email_messages:
            try:
                self._send(message)
                count += 1
            except ResendDeliveryError:
                if not self.fail_silently:
                    raise
        return count

    def _send(self, message):
        key = settings.RESEND_API_KEY
        if not key:
            raise ResendDeliveryError('Email service is not configured.')
        payload = {
            'from': message.from_email,
            'to': message.to,
            'subject': message.subject,
            'text': message.body,
        }
        if message.cc:
            payload['cc'] = message.cc
        if message.bcc:
            payload['bcc'] = message.bcc
        if message.reply_to:
            payload['reply_to'] = message.reply_to
        attachments = []
        for attachment in message.attachments:
            if not isinstance(attachment, tuple) or len(attachment) != 3:
                raise ResendDeliveryError('Unsupported email attachment.')
            filename, content, mimetype = attachment
            if isinstance(content, str):
                content = content.encode('utf-8')
            attachments.append({'filename': filename, 'content': base64.b64encode(content).decode('ascii'), 'content_type': mimetype})
        if attachments:
            payload['attachments'] = attachments
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
        # Identical retries reuse the provider's idempotency key. An administrator's
        # changed classroom URL changes the payload and permits a new notification.
        identity = message.extra_headers.get('Message-ID', '')
        digest = hashlib.sha256(identity.encode('utf-8') + b'\n' + body).hexdigest()
        request = Request('https://api.resend.com/emails', data=body, method='POST', headers={
            'Authorization': 'Bearer ' + key,
            'Content-Type': 'application/json',
            'Idempotency-Key': 'recitera-' + digest,
            'User-Agent': 'Recitera-Booking-Mail/1.0',
        })
        try:
            with urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                result = json.loads(response.read(65536))
                if response.status not in [200, 201, 202] or not isinstance(result.get('id'), str) or not result['id']:
                    raise ResendDeliveryError('Email provider did not accept the message.')
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            raise ResendDeliveryError('Email provider is unavailable or sender verification is incomplete.') from None
