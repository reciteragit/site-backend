from django.core.exceptions import ValidationError

def validate_languages(value):
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError('Enter a nonempty JSON array of language names, e.g. ["English", "Arabic"].')
