"""Pure domain rules.

No Flask, no database, no HTML in here. Give these functions a value and they
hand back a rule answer. Because they have no hidden dependencies, this is the
easiest module in the app to read top-to-bottom and to unit test.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Internal state -> the text shown to a user.
STATE_LABELS = {
    'achieved': 'Achieved',
    'unassessed': 'Not assessed',
    'cooling_off': 'Available to retry',
}


def achievement_state(competency_id, states):
    # states maps competency_id -> recorded status. No row means 'unassessed'.
    return states.get(competency_id, 'unassessed')


# Retry rule (decided June 15): after a "Not passed", a competency unlocks two
# CALENDAR days later at 8 AM Toronto time (Tue fail -> Thu 8 AM). The hour of the
# attempt does not matter, only its date. Display only for now: nothing blocks an
# early re-mark yet (whether to enforce is pending Dave, issue #1).
TORONTO = ZoneInfo("America/Toronto")
RETRY_DAYS = 2
RETRY_HOUR = 8


def parse_timestamp(value):
    # date_recorded is stored as UTC text by SQLite CURRENT_TIMESTAMP, and the
    # seed rows omit seconds, so try both formats and tag the result as UTC.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def retry_unlock(date_recorded):
    # The moment a cooling-off competency becomes retryable, as an aware datetime.
    # Convert the stored UTC time to Toronto local FIRST (so 8 AM means 8 AM there,
    # and EST/EDT is handled automatically), then take that date + 2 days at 08:00.
    recorded = parse_timestamp(date_recorded)
    if recorded is None:
        return None
    local = recorded.astimezone(TORONTO)
    unlock_day = local.date() + timedelta(days=RETRY_DAYS)
    return datetime(unlock_day.year, unlock_day.month, unlock_day.day,
                    RETRY_HOUR, 0, tzinfo=TORONTO)


def retry_available(date_recorded):
    # True once the unlock moment has passed (or if the timestamp is unparseable,
    # so a bad row never traps a student in cooling off).
    unlock = retry_unlock(date_recorded)
    if unlock is None:
        return True
    return datetime.now(timezone.utc) >= unlock


def cooling_off_label(date_recorded):
    # Non-negative, student-facing wording (decided June 15: replace "Cooling off").
    unlock = retry_unlock(date_recorded)
    if unlock is None:
        return STATE_LABELS['cooling_off']
    if datetime.now(timezone.utc) >= unlock:
        return 'Available to retry now'
    return 'Available to retry ' + unlock.strftime('%A 8 AM')
