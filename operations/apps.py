from django.apps import AppConfig
class OperationsConfig(AppConfig):
    name='operations'
    verbose_name='Operations & Telegram'
    def ready(self):
        from . import signals
