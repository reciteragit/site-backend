import hashlib,logging,threading,time
_guard=threading.local()
class SafeTelegramErrorHandler(logging.Handler):
    def emit(self,record):
        if record.levelno<logging.ERROR or getattr(_guard,'active',False):return
        _guard.active=True
        try:
            from .outbox import queue
            kind=type(record.exc_info[1]).__name__ if record.exc_info and record.exc_info[1] else 'Error'
            request=getattr(record,'request',None)
            path=getattr(getattr(request,'resolver_match',None),'route','unresolved route' if request else '')[:200]
            fingerprint=hashlib.sha256((record.name+'|'+kind+'|'+path+'|'+str(int(time.time()//60))).encode()).hexdigest()
            queue('runtime:'+fingerprint,'errors','Server error',{'Logger':record.name,'Level':record.levelname,'Exception type':kind,'Route pattern':path})
        except Exception:pass
        finally:_guard.active=False
