from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from rest_framework import serializers


def zone(value):
    try: return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError): raise serializers.ValidationError('Choose a valid IANA time zone, for example America/Toronto.')


def local_time(value, timezone_name):
    try: naive = datetime.fromisoformat(value)
    except (ValueError, TypeError): raise serializers.ValidationError('Enter a local date and time.')
    if naive.tzinfo: raise serializers.ValidationError('Enter local time without an offset; the selected time zone is applied by the server.')
    tz = zone(timezone_name)
    possibilities = set()
    for fold in [0,1]:
        utc = naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None)==naive: possibilities.add(utc)
    if len(possibilities)!=1: raise serializers.ValidationError('This local time is missing or ambiguous because of daylight saving time. Choose a different time.')
    return possibilities.pop()
