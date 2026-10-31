from django.apps import AppConfig
class CRMConfig(AppConfig):
    name='crm'
    verbose_name='CRM & onboarding'
    def ready(self):
        from . import signals
