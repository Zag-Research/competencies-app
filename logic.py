"""Pure domain rules.

No Flask, no database, no HTML in here. Give these functions a value and they
hand back a rule answer. Because they have no hidden dependencies, this is the
easiest module in the app to read top-to-bottom and to unit test.
"""
from datetime import date, datetime, timedelta, timezone
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


# Studio sessions (#17). The studio runs three times a week: Tuesday 4-5 PM,
# Wednesday 3-6 PM, Thursday 9 AM-12 PM. Python's weekday() has Monday at 0, so
# those are 1, 2 and 3.
#
# These are derived from the weekly pattern rather than read from a table of term
# dates, because the Fall 2026 calendar is not settled. The cost is that this
# cannot know about holidays or reading week, so it may offer a day that does not
# actually run. Replace with a seeded studios table once the real dates exist.
STUDIO_WEEKDAYS = (1, 2, 3)
STUDIO_LOOKAHEAD = 6


def today_toronto():
    # "Today" for scheduling is the local studio day, not UTC: at 9 PM Toronto the
    # UTC date has already rolled over, and a student signing up then means today.
    return datetime.now(timezone.utc).astimezone(TORONTO).date()


def is_studio_day(iso_date):
    try:
        return date.fromisoformat(iso_date).weekday() in STUDIO_WEEKDAYS
    except (TypeError, ValueError):
        return False


def upcoming_studios(count=STUDIO_LOOKAHEAD, today=None):
    """The next `count` studio days as ISO date strings, including today if it is one."""
    day = today or today_toronto()
    out = []
    while len(out) < count:
        if day.weekday() in STUDIO_WEEKDAYS:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def next_studio(today=None):
    # The day a sign-up defaults to: today when the studio runs, else the next one.
    return upcoming_studios(1, today)[0]


def studio_label(iso_date):
    # '2026-07-28' -> 'Tuesday, July 28'. Built without %-d, which is not portable.
    try:
        d = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return iso_date
    return d.strftime('%A, %B ') + str(d.day)


# Sign-up limits per studio session (#22). Two rules at once:
#   - at most `cap` competencies in the session, and
#   - the two courses no more than 1 apart, so a student makes progress on both
#     instead of bingeing one (2 of one and 1 of the other is fine; 3 and 0 is not).
#
# `course_counts` is {course: how many signed up this session}, and MUST include a
# 0 for a course the student takes but has not picked, or a lopsided "2 and 0"
# would look balanced. A student in a single course has one entry, so max == min
# and only the cap applies.
def session_signup_ok(course_counts, cap):
    counts = list(course_counts.values())
    if sum(counts) > cap:
        return False
    if counts and max(counts) - min(counts) > 1:
        return False
    return True
