import uuid
import threading
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from academy.tests import fixture, stripe_session
from academy.models import Slot, CartItem, Booking, Order, EmailDelivery
from academy.authentication import issue_token
from academy.availability import ScheduleInput, save_schedule
from academy.services import available_queryset, expire_holds, process_event

User=get_user_model()

class FreeTrialTests(TestCase):
    def setUp(self):
        self.student,_,self.teacher,self.paid,self.config,self.api=fixture()
        self.paid.ends_at=self.paid.starts_at+timedelta(minutes=45);self.paid.save()
        self.trial=Slot.objects.create(teacher=self.teacher,kind='trial',starts_at=self.paid.starts_at,ends_at=self.paid.starts_at+timedelta(minutes=15))
    def checkout(self, slot, client=None, user=None, request_id=None):
        CartItem.objects.create(user=user or self.student,slot=slot)
        return (client or self.api).post('/api/academy/checkout/',{'request_id':str(request_id or uuid.uuid4()),'timezone':'Asia/Tehran'},format='json')
    def other(self):
        user=User.objects.create_user('trial-second@example.com',email='trial-second@example.com')
        api=APIClient();api.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(user));return user,api
    def test_free_trial_confirms_without_stripe_and_is_idempotent(self):
        self.config.delete();request_id=uuid.uuid4()
        with patch('academy.views.client') as gateway:
            response=self.checkout(self.trial,request_id=request_id)
            self.assertEqual(response.status_code,200,response.data);gateway.assert_not_called()
            replay=self.api.post('/api/academy/checkout/',{'request_id':str(request_id),'timezone':'UTC'},format='json')
            self.assertEqual(replay.status_code,200);gateway.assert_not_called()
        order=Order.objects.get();booking=Booking.objects.get()
        self.assertEqual(order.mode,'free');self.assertEqual(order.amount,0);self.assertEqual(order.status,'paid')
        self.assertEqual(booking.status,'confirmed');self.assertEqual(booking.amount,0)
        self.assertEqual(EmailDelivery.objects.count(),2);self.assertFalse(CartItem.objects.exists())
        self.assertFalse(available_queryset().filter(pk=self.paid.pk).exists())
        user,api=self.other();self.assertEqual(self.checkout(self.paid,api,user).status_code,409)
    def test_paid_reservation_hides_overlapping_trial(self):
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            self.assertEqual(self.checkout(self.paid).status_code,200)
        self.assertFalse(available_queryset().filter(pk=self.trial.pk).exists())
        user,api=self.other();self.assertEqual(self.checkout(self.trial,api,user).status_code,409)
    def test_cart_uses_server_prices_not_client_input(self):
        result=self.api.post('/api/academy/cart/',{'slot_id':str(self.trial.pk),'price':'999','kind':'class'},format='json')
        self.assertEqual(result.status_code,200);self.assertEqual(result.data[0]['price'],'0');self.assertEqual(result.data[0]['kind'],'trial')
    def test_mixed_cart_does_not_confirm_free_session_before_payment(self):
        later=Slot.objects.create(teacher=self.teacher,kind='trial',starts_at=self.paid.ends_at,ends_at=self.paid.ends_at+timedelta(minutes=15))
        CartItem.objects.create(user=self.student,slot=later)
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            self.assertEqual(self.checkout(self.paid).status_code,200)
            args=gateway.return_value.v1.checkout.sessions.create.call_args.args[0]
            self.assertEqual(len(args['line_items']),1)
        self.assertEqual(Booking.objects.filter(status='held').count(),2)
        self.assertEqual(Order.objects.get().amount,self.teacher.teacher.price)
        self.assertFalse(EmailDelivery.objects.exists())
    def test_late_paid_webhook_cannot_replace_overlapping_confirmed_free_trial(self):
        with patch('academy.views.client') as gateway:
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            self.checkout(self.paid)
        paid_order=Order.objects.get();Order.objects.filter(pk=paid_order.pk).update(expires_at=timezone.now()-timedelta(seconds=1));expire_holds()
        user,api=self.other();self.assertEqual(self.checkout(self.trial,api,user).status_code,200)
        event={'id':'evt_late_trial_conflict','type':'checkout.session.completed','livemode':False,'data':{'object':{'id':paid_order.stripe_session_id,'client_reference_id':str(paid_order.pk),'metadata':{'academy_order_id':str(paid_order.pk)},'amount_total':int(paid_order.amount*100),'currency':'cad','payment_status':'paid'}}}
        self.assertEqual(process_event(event)[1],200);paid_order.refresh_from_db();self.assertEqual(paid_order.status,'payment_review')
        self.assertEqual(Booking.objects.filter(status='confirmed').count(),1)
    def test_overlapping_session_plans_are_separate_and_dst_safe(self):
        Slot.objects.filter(pk__in=[self.paid.pk,self.trial.pk]).update(active=False)
        start=(timezone.now()+timedelta(days=3)).date()
        data={'kind':'class','timezone':'Africa/Cairo','start_date':str(start),'end_date':str(start+timedelta(days=7)),'duration_minutes':45,'weekly':[{'day':d,'ranges':[{'start':'12:00','end':'13:30'}]} for d in range(7)]}
        serializer=ScheduleInput(data=data);serializer.is_valid(raise_exception=True);save_schedule(self.teacher,dict(serializer.validated_data))
        data.update(kind='trial',duration_minutes=15)
        serializer=ScheduleInput(data=data);serializer.is_valid(raise_exception=True);result=save_schedule(self.teacher,dict(serializer.validated_data))
        self.assertEqual(result['created'],48);self.assertEqual(result['skipped_overlap'],0)
        self.assertEqual(self.teacher.availability_schedules.count(),2)
        data['duration_minutes']=45;self.assertFalse(ScheduleInput(data=data).is_valid())

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL locks')
class CrossKindConcurrencyTests(TransactionTestCase):
    def test_simultaneous_paid_and_free_overlapping_slots_have_only_one_winner(self):
        student,_,teacher,paid,config,first=fixture()
        trial=Slot.objects.create(teacher=teacher,kind='trial',starts_at=paid.starts_at,ends_at=paid.starts_at+timedelta(minutes=15))
        other=User.objects.create_user('trial-race@example.com',email='trial-race@example.com')
        second=APIClient();second.credentials(HTTP_AUTHORIZATION='Bearer '+issue_token(other))
        CartItem.objects.create(user=student,slot=paid);CartItem.objects.create(user=other,slot=trial)
        barrier=threading.Barrier(2);statuses=[];errors=[]
        def run(client):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                statuses.append(client.post('/api/academy/checkout/',{'request_id':str(uuid.uuid4()),'timezone':'UTC'},format='json').status_code)
            except Exception as error:errors.append(type(error).__name__)
            finally:close_old_connections()
        with patch('academy.views.client') as gateway,patch('academy.notifications.flush_mail'):
            gateway.return_value.v1.checkout.sessions.create.side_effect=stripe_session
            threads=[threading.Thread(target=run,args=(c,)) for c in [first,second]]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=20)
        self.assertFalse(errors,errors);self.assertEqual(sorted(statuses),[200,409]);self.assertEqual(Booking.objects.filter(status__in=['held','confirmed']).count(),1)
