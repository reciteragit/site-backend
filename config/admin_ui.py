"""Recitera branding and permission-aware navigation for the MIT-licensed Unfold theme."""
from django.apps import apps
from django.templatetags.static import static
from django.urls import reverse


def permitted(request, label):
    from django.contrib import admin
    model = apps.get_model(label)
    model_admin = admin.site._registry.get(model)
    return bool(model_admin and model_admin.has_module_permission(request) and (model_admin.has_view_permission(request) or model_admin.has_change_permission(request)))


def item(title, icon, label):
    app, model = label.lower().split('.')
    return {'title':title, 'icon':icon, 'link':lambda request:reverse(f'admin:{app}_{model}_changelist'), 'permission':lambda request:permitted(request,label)}


UNFOLD = {
    'SITE_TITLE':'Recitera Admin',
    'SITE_HEADER':'RECITERA',
    'SITE_SUBHEADER':'Academy management',
    'SITE_SYMBOL':'auto_stories',
    'SITE_URL':'https://www.recitera.com',
    'SHOW_HISTORY':True,
    'SHOW_VIEW_ON_SITE':True,
    'DASHBOARD_CALLBACK':'config.dashboard.dashboard',
    'STYLES':[lambda request:static('recitera/admin.css')],
    'COLORS':{'primary':{
        '50':'#f0f6f2','100':'#dceae1','200':'#bed6c7','300':'#95b9a3','400':'#6c9980','500':'#4c7c63','600':'#38624d','700':'#2b4d3e','800':'#233f33','900':'#1c332a','950':'#0e1c16',
    }},
    'SIDEBAR':{
        'show_search':True,
        'show_all_applications':True,
        'navigation':[
            {'items':[{'title':'Overview','icon':'space_dashboard','link':lambda request:reverse('admin:index')}]},
            {'title':'Academy','separator':True,'items':[
                item('Teacher profiles','school','catalog.Teacher'),
                item('Teaching & classrooms','video_camera_front','academy.TeachingProfile'),
                item('Class bookings','calendar_month','academy.Booking'),
                item('Cancellation requests','event_busy','academy.CancellationRequest'),
                item('Available time slots','schedule','academy.Slot'),
                item('Recorded courses','play_lesson','catalog.Course'),
                item('Episode videos','video_library','learning.Episode'),
                item('Course packages','inventory_2','learning.CourseBundle'),
                item('Learner course access','how_to_reg','learning.Enrollment'),
                item('Learning progress','monitoring','learning.EpisodeProgress'),
            ]},
            {'title':'People & applications','separator':True,'items':[
                item('Teacher applications','person_add','catalog.TeacherApplication'),
                item('Scholarships','volunteer_activism','catalog.ScholarshipApplication'),
                item('Volunteers','diversity_1','catalog.VolunteerApplication'),
                item('User profiles','badge','academy.Profile'),
                item('Newsletter','mail','catalog.NewsletterSubscriber'),
            ]},
            {'title':'Payments','separator':True,'items':[
                item('Class orders','receipt_long','academy.Order'),
                item('Discount codes','sell','catalog.DiscountCode'),
                item('Donations & payments','payments','catalog.PaymentOrder'),
                item('Donors','favorite','catalog.Donor'),
                item('Payment pages','link','catalog.PaymentItem'),
                item('Stripe connection','credit_card','catalog.StripeSettings'),
            ]},
            {'title':'Administration','separator':True,'items':[
                item('Confirmation emails','outgoing_mail','academy.EmailDelivery'),
                item('Reminders & cancellation emails','notifications','academy.BookingNotice'),
                item('Users','manage_accounts','auth.User'),
                item('Groups & permissions','admin_panel_settings','auth.Group'),
                item('Google connections','account_circle','academy.GoogleIdentity'),
                item('Stripe events','sync','catalog.StripeEvent'),
            ]},
        ],
    },
    'COMMAND':{'search_models':True,'show_history':True},
}
