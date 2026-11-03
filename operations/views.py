from django.core.exceptions import PermissionDenied
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .sender import flush
from .outbox import connection,valid_connection


class TelegramWorker(APIView):
    permission_classes=[AllowAny];authentication_classes=[]
    def get(self,request):
        from academy.workflow_auth import worker_authorized
        if not worker_authorized(request):raise PermissionDenied('Not authorized.')
        config=connection()
        return Response({'telegram_configured':bool(config.enabled and valid_connection(config)),'telegram_sent':flush(8)})
