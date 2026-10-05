"""Timezone-aware schedules. Persist UTC instants; reject ambiguous wall times."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re


def local_instant(wall, zone):
    tz = ZoneInfo(zone)
    first, second = wall.replace(tzinfo=tz, fold=0), wall.replace(tzinfo=tz, fold=1)
    if first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != wall:
        raise ValueError('That local time does not exist because clocks change. Choose another time.')
    if first.utcoffset() != second.utcoffset():
        raise ValueError('That local time occurs twice. Provide an ISO time with a UTC offset.')
    return first.timestamp()


def parse_when(value, zone, now):
    tz = ZoneInfo(zone)
    relative = re.fullmatch(r'in (\d+) (minutes?|hours?|days?)', value.strip(), re.I)
    if relative:
        seconds = int(relative[1]) * (86400 if relative[2].startswith('day') else 3600 if relative[2].startswith('hour') else 60)
        return now + seconds
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if 'T' not in value and ' ' not in value: raise ValueError('A time is required.')
        return date.timestamp() if date.tzinfo else local_instant(date, zone)
    except ValueError:
        pass
    match = re.fullmatch(r'(today|tomorrow|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?', value.strip(), re.I)
    if not match: raise ValueError('Use an exact date and time, tomorrow at 3pm, or in 20 minutes.')
    day, hour, minute, suffix = match.groups(); hour, minute = int(hour), int(minute or 0)
    if suffix:
        if not 1 <= hour <= 12: raise ValueError('Use an hour from 1 to 12 with AM or PM.')
        hour = hour % 12 + (12 if suffix.lower() == 'pm' else 0)
    base = datetime.fromtimestamp(now, tz).replace(tzinfo=None, hour=hour, minute=minute, second=0, microsecond=0)
    day = day.lower()
    if day == 'tomorrow': base += timedelta(days=1)
    elif day != 'today':
        weekday = ['mon','tue','wed','thu','fri','sat','sun'].index(day[:3])
        days = (weekday-base.weekday()) % 7
        base += timedelta(days=days or (7 if local_instant(base, zone) <= now else 0))
    return local_instant(base, zone)


def next_fire(schedule, zone, after):
    from croniter import croniter
    from dateutil.rrule import rrulestr
    tz = ZoneInfo(zone)
    base = datetime.fromtimestamp(after, tz)
    if schedule['type'] == 'cron':
        # Iterate local wall times, then convert, avoiding elapsed-hour DST drift.
        iterator = croniter(schedule['cron'], base.replace(tzinfo=None), max_years_between_matches=5)
        for _ in range(500):
            wall = iterator.get_next(datetime)
            try: instant = local_instant(wall, zone)
            except ValueError: continue
            if instant > after: return instant
        raise ValueError('No valid occurrence found.')
    start=datetime.fromisoformat(schedule['startsAt'].replace('Z','+00:00'))
    if start.tzinfo is None:raise ValueError('RRULE startsAt requires a UTC offset.')
    rule = rrulestr(schedule['rrule'], dtstart=start.astimezone(tz))
    candidate = rule.after(base, inc=False)
    if candidate is None: return None
    return local_instant(candidate.replace(tzinfo=None), zone)
