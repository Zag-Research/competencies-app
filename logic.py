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
# CALENDAR days later at 8 AM Toronto time (Tue fail -> Thu 8 AM). If that lands on
# a non-studio day it rolls forward to the next studio day (#25): a Friday fail would
# otherwise read "retry Sunday 8 AM", but the soonest they could actually retry is the
# next session anyway. The hour of the attempt does not matter, only its date.
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
    # +2 calendar days, then roll forward to the next studio day if that is a
    # weekend or Monday (#25). studio_on_or_after is defined below; it resolves at
    # call time, so the forward reference is fine.
    unlock_day = studio_on_or_after(local.date() + timedelta(days=RETRY_DAYS))
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
# These come from the weekly pattern rather than a full term calendar. Statutory
# holidays need no special handling: across both the Fall 2026 and Winter 2027 terms
# they all fall on Mondays or Fridays, off the studio's days. The reading weeks DO land
# on studio days, so they are listed below and skipped. (Term start/end are not enforced
# yet, so an out-of-term Tue/Wed/Thu is still offered; harmless because the studio is not
# in use then. Load real term ranges here if that ever matters.)
STUDIO_WEEKDAYS = (1, 2, 3)
STUDIO_LOOKAHEAD = 6

# University reading weeks (TMU 2026-2027 calendar): the studio does not run on these
# days even though they are Tue/Wed/Thu, because the lab is closed and classes are off.
STUDIO_BREAKS = (
    (date(2026, 10, 13), date(2026, 10, 16)),  # Fall study week
    (date(2027, 2, 16), date(2027, 2, 19)),    # Winter study week
)

# Term boundaries (TMU 2026-2027 calendar). With STUDIO_WEEKDAYS and STUDIO_BREAKS
# these are all it takes to *count* the studio's sessions instead of hard-coding a
# number: walking this range yields exactly the 36 sessions the course is built
# around, which is the check that these three facts agree with each other.
TERM_START = date(2026, 9, 8)   # first day of Fall term undergraduate classes
TERM_END = date(2026, 12, 7)    # last day of Fall term classes


def in_studio_break(day):
    """True if `day` (a date) falls in a reading week, when the studio is closed."""
    return any(start <= day <= end for (start, end) in STUDIO_BREAKS)


def today_toronto():
    # "Today" for scheduling is the local studio day, not UTC: at 9 PM Toronto the
    # UTC date has already rolled over, and a student signing up then means today.
    return datetime.now(timezone.utc).astimezone(TORONTO).date()


def is_studio_day(iso_date):
    try:
        d = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return False
    return d.weekday() in STUDIO_WEEKDAYS and not in_studio_break(d)


def studio_on_or_after(day):
    """The first studio day on or after `day` (returns `day` unchanged if it is one)."""
    while day.weekday() not in STUDIO_WEEKDAYS or in_studio_break(day):
        day += timedelta(days=1)
    return day


def upcoming_studios(count=STUDIO_LOOKAHEAD, today=None):
    """The next `count` studio days as ISO date strings, including today if it is one."""
    day = today or today_toronto()
    out = []
    while len(out) < count:
        if day.weekday() in STUDIO_WEEKDAYS and not in_studio_break(day):
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


# Pace (#50). A student should find out they are drifting in week 4, not week 11, so
# their page compares two fractions: how much of their competency list is done, and
# how much of the studio has happened. Sessions, not calendar days, are the honest
# denominator; reading week should not make anyone look behind.
#
# How far the two percentages must diverge before the page says anything about it.
# Inside this band a student is on pace, and "you are 2% behind" is noise dressed up
# as a warning.
PACE_TOLERANCE = 5


def studio_days():
    """Every studio day in the term, in order."""
    days = []
    day = TERM_START
    while day <= TERM_END:
        if day.weekday() in STUDIO_WEEKDAYS and not in_studio_break(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def term_elapsed(today=None):
    """How much of the studio is behind us, as (sessions_done, sessions_total).

    A session counts once it is over, so the one a student is sitting in does not
    yet count against them. Being told you are behind on the strength of a session
    still in progress would be both wrong and discouraging.
    """
    today = today or today_toronto()
    sessions = studio_days()
    return sum(1 for day in sessions if day < today), len(sessions)


def percent(part, whole):
    """`part` of `whole` as a whole number percentage; 0 when there is no whole.

    Rounded, because a student reading '32.7%' learns nothing that '33%' does not
    already tell them.
    """
    return round(100 * part / whole) if whole else 0


def pace_note(done_pct, term_pct, elapsed):
    """The one line of encouragement shown beneath the two percentages.

    Deliberately a carrot: ahead reads as praise, behind reads as a nudge, and
    neither reads as a failure. `elapsed` distinguishes 'you have done nothing'
    from 'nothing has happened yet', which deserve very different sentences.
    """
    if not elapsed:
        return 'The studio has not started yet. Nothing to catch up on.'
    gap = done_pct - term_pct
    if gap >= PACE_TOLERANCE:
        return 'You are ahead of where the studio is. Nice work.'
    if gap <= -PACE_TOLERANCE:
        return 'The studio is a little ahead of you. Worth picking up the pace.'
    return 'You are keeping pace with the studio.'


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
