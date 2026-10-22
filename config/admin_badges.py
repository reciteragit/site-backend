from django.utils.html import format_html


def status_badge(status):
    tone={'paid':'success','confirmed':'success','held':'warning','pending':'warning','registered':'neutral','payment_review':'danger','failed':'danger','expired':'neutral'}.get(status,'neutral')
    return format_html('<span class="rc-badge rc-badge-{}">{}</span>',tone,status.replace('_',' ').title())
