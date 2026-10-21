"""Expand a finite weekly local-time schedule into protected UTC booking slots."""
from datetime import datetime, time, timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import AvailabilitySchedule, TeachingProfile, Slot
from .timezones import zone, local_time


class TimeRange(serializers.Serializer):
    start = serializers.RegexField(r'^([01]\d|2[0-3]):[0-5]\d$')
    end = serializers.RegexField(r'^([01]\d|2[0-3]):[0-5]\d$')


class DayRanges(serializers.Serializer):
    day = serializers.IntegerField(min_value=0, max_value=6)  # Monday = 0
    ranges = TimeRange(many=True, max_length=6)


class ScheduleInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["class", "trial"], default="class")
    timezone = serializers.CharField(max_length=100)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    duration_minutes = serializers.IntegerField(min_value=15, max_value=180)
    weekly = DayRanges(many=True, min_length=7, max_length=7)

    def validate(self, data):
        tz = zone(data['timezone'])
        today = timezone.now().astimezone(tz).date()
        if data['start_date'] < today or data['end_date'] < data['start_date'] or data['end_date'] > today + timedelta(days=179):
            raise serializers.ValidationError('Choose a date range starting today or later, within the next 180 days.')
        if len({d['day'] for d in data['weekly']}) != 7:
            raise serializers.ValidationError('Include each weekday exactly once.')
        duration = data['duration_minutes']
        if data['kind'] == 'trial' and duration != 15:
            raise serializers.ValidationError('Free trial sessions must be 15 minutes.')
        for day in data['weekly']:
            ranges = sorted(day['ranges'], key=lambda r: r['start'])
            last = None
            for r in ranges:
                start = datetime.strptime(r['start'], '%H:%M')
                end = datetime.strptime(r['end'], '%H:%M')
                if end <= start or (end - start).total_seconds() < duration * 60 or (last and start < last):
                    raise serializers.ValidationError('Ranges must not overlap, must end on the same day, and must fit at least one full class.')
                last = end
            day['ranges'] = ranges
        return data


def schedule_data(schedule):
    return {'kind': schedule.kind, 'timezone': schedule.timezone, 'start_date': schedule.start_date.isoformat(), 'end_date': schedule.end_date.isoformat(), 'duration_minutes': schedule.duration_minutes, 'weekly': schedule.weekly}


def save_schedule(profile, data):
    now = timezone.now()
    duration = timedelta(minutes=data['duration_minutes'])
    weekly = {d['day']: d['ranges'] for d in data['weekly']}
    desired = set()
    skipped_dst = 0
    day = data['start_date']
    while day <= data['end_date']:
        for r in weekly[day.weekday()]:
            current = datetime.combine(day, time.fromisoformat(r['start']))
            until = datetime.combine(day, time.fromisoformat(r['end']))
            while current + duration <= until:
                try:
                    start = local_time(current.isoformat(), data['timezone'])
                    end = local_time((current + duration).isoformat(), data['timezone'])
                    if end - start != duration:
                        raise serializers.ValidationError('DST transition')
                except serializers.ValidationError:
                    skipped_dst += 1
                else:
                    if now + timedelta(hours=1) < start < now + timedelta(days=180):
                        desired.add((start, end))
                current += duration
                if len(desired) > 3000:
                    raise serializers.ValidationError('This schedule exceeds 3,000 classes. Choose a shorter date range or fewer hours.')
        day += timedelta(days=1)
    with transaction.atomic():
        profile = TeachingProfile.objects.select_for_update().get(pk=profile.pk)
        schedule, _ = AvailabilitySchedule.objects.get_or_create(teacher=profile, kind=data.get('kind', 'class'), defaults=data)
        existing = list(Slot.objects.filter(teacher=profile, ends_at__gt=now).prefetch_related('bookings'))
        protected = [s for s in existing if any(b.status in ['held', 'confirmed'] for b in s.bookings.all())]
        manual = [s for s in existing if s.active and (s.schedule_id is None or s.starts_at <= now)]
        blockers = {s.pk: s for s in protected + manual}.values()
        allowed, skipped_overlap = set(), 0
        for start, end in desired:
            if any(s.starts_at < end and s.ends_at > start for s in blockers):
                skipped_overlap += 1
            else:
                allowed.add((start, end))
        free = [s for s in existing if s.schedule_id == schedule.pk and s.starts_at > now and s.pk not in {p.pk for p in protected}]
        keep = {}
        for s in free:
            key = (s.starts_at, s.ends_at)
            if s.active and key in allowed and key not in keep:
                keep[key] = s
        remove = [s.pk for s in free if s.active and s.pk not in {v.pk for v in keep.values()}]
        Slot.objects.filter(pk__in=remove).update(active=False)
        create = [Slot(teacher=profile, schedule=schedule, kind=data.get('kind', 'class'), starts_at=start, ends_at=end) for start, end in sorted(allowed - keep.keys())]
        Slot.objects.bulk_create(create)
        for key, value in data.items():
            setattr(schedule, key, value)
        schedule.save()
        # Existing slots/bookings retain their UTC instants when the teaching zone changes.
        profile.timezone = data['timezone']
        profile.save(update_fields=['timezone'])
    return {**schedule_data(schedule), 'created': len(create), 'available': len(allowed), 'removed': len(remove), 'preserved_reserved': len(protected), 'skipped_dst': skipped_dst, 'skipped_overlap': skipped_overlap}
