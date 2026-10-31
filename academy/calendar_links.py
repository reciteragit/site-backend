from datetime import timezone
from urllib.parse import urlencode


def calendar_links(booking):
    title='Recitera class with '+booking.teacher_name
    details='Join your class: '+booking.meeting_url+'\nBooking: '+str(booking.pk)
    start=booking.slot.starts_at.astimezone(timezone.utc)
    end=booking.slot.ends_at.astimezone(timezone.utc)
    google='https://calendar.google.com/calendar/render?'+urlencode({'action':'TEMPLATE','text':title,'dates':start.strftime('%Y%m%dT%H%M%SZ')+'/'+end.strftime('%Y%m%dT%H%M%SZ'),'details':details,'location':booking.meeting_url})
    outlook='https://outlook.live.com/calendar/0/deeplink/compose?'+urlencode({'path':'/calendar/action/compose','rru':'addevent','subject':title,'startdt':start.isoformat(),'enddt':end.isoformat(),'body':details,'location':booking.meeting_url})
    return {'google':google,'outlook':outlook,'apple':f'/api/academy/bookings/{booking.pk}/calendar'}
