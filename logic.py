"""Pure domain rules.

No Flask, no database, no HTML in here. Give these functions a value and they
hand back a rule answer. Because they have no hidden dependencies, this is the
easiest module in the app to read top-to-bottom and to unit test.
"""
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Internal state -> the text shown to a user.
STATE_LABELS = {
    'achieved': 'Achieved',
    'unassessed': 'Not assessed',
    'cooling_off': 'Available to retry',
}

# What staff press, and what the undo banner calls it afterwards. Dave asked for
# "Deferred" on Sept 2: the outcome is a two day wait before retrying, not a failure,
# and "Not passed" made it sound like one (#126). Students already saw the kinder
# "Available to retry" in STATE_LABELS above; this is the half they never see.
#
# One constant rather than the four string literals it replaces, because those had
# already drifted apart once between the marking page and the queue.
DEFER_LABEL = 'Deferred'


def achievement_state(competency_id, states):
    # states maps competency_id -> recorded status. No row means 'unassessed'.
    return states.get(competency_id, 'unassessed')


# Retry rule (decided June 15): after a deferral, a competency unlocks two
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
# on studio days, so they are listed below and skipped.
#
# Sign-up still offers any Tue/Wed/Thu, in or out of term, which is harmless because the
# studio is not running then. TERM_START/TERM_END below bound the term for counting
# sessions (#50); they are not enforced as a sign-up window.
STUDIO_WEEKDAYS = (1, 2, 3)

# Which of those weekdays each course actually meets on (#81). From Dave's Fall 2026
# sections in the TMU timetable, all four components his, all in George Vari Rm 206:
#
#   Tuesday    CPS213 LAB then CPS109 LAB     both courses
#   Wednesday  CPS213 LEC                     213 only
#   Thursday   CPS109 LEC                     109 only
#
# This is what makes an attendance fraction honest for a student taking only one of
# the two. Measured against all three days, somebody registered in CPS109 alone is
# counted absent every Wednesday of the term, for a session they were never in, and
# the instructor's rule is a penalty for missing more than half.
#
# A course missing from here falls back to every studio day, so an unknown course
# behaves as it did before rather than silently reporting a smaller denominator.
COURSE_WEEKDAYS = {
    'CPS109': (1, 3),
    'CPS213': (1, 2),
}
# Fallback only. The real value is the `studio_lookahead` setting, read by callers, so
# how far ahead students can book is a config change rather than a deploy (#17).
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


def days_ago(n, today=None):
    """`n` days before today, as an ISO date string.

    A cutoff for "recently", written once here because date_recorded is stored as
    text: comparing 'YYYY-MM-DD HH:MM' against a plain 'YYYY-MM-DD' sorts correctly
    only because the date comes first, which is worth stating rather than rely on.
    """
    return ((today or today_toronto()) - timedelta(days=n)).isoformat()


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


# Lab machines (#46). Only one action is restricted to being physically in the
# studio: a student entering their seat number. Dave settled the scope on that issue:
# "anybody can open it anywhere and has CAS authentication ... Seat number only is an
# option for a student logged into a lab machine in the lab."
#
# The test is not an IP range. CS systems (Aug 17): "All lab machines have an internal
# dns entry: ie. eng201-01 ... The app should do a reverse dns lookup of the ip address
# accessing your app. The prefix eng20x-xx format would point to the corresponding lab
# machine." They also confirmed the machines have unique routable IPs with no NAT in
# front, so the address the server sees is genuinely the client's.
#
# This half is the rule; the reverse lookup itself lives in common.py, because a DNS
# call is exactly the hidden dependency this module is meant not to have.
LAB_HOST_PATTERN = r'eng\d{3}-\d+'


def is_lab_host(hostname, pattern=None):
    """True if a resolved hostname names one of the studio lab machines.

    Matches on the first label only, so 'eng201-01.cs.torontomu.ca' and 'eng201-01'
    both pass and a name that merely contains the pattern later on does not.
    """
    if not hostname:
        return False
    return re.fullmatch(pattern or LAB_HOST_PATTERN,
                        hostname.split('.')[0], re.IGNORECASE) is not None


# Sign-up limits per studio session (#22). Two rules at once:
#   - at most `cap` competencies in the session, and
#   - the two courses no more than 1 apart, so a student makes progress on both
#     instead of bingeing one (2 of one and 1 of the other is fine; 3 and 0 is not).
#
# `course_counts` is {course: how many signed up this session}, and MUST include a
# 0 for a course the student takes but has not picked, or a lopsided "2 and 0"
# would look balanced. A student in a single course has one entry, so max == min
# and only the cap applies.
# Catching up after a missed week (#70). The three-per-session cap (#22) is a
# spreading rule, not a rationing one: it stops a student doing forty in one sitting.
# Someone who was ill did not choose to bunch their work, so the cap punishes them for
# something it was never aimed at.
#
# Dave set the size of this: an ACR can cover three days, so a student can lose a whole
# week of sessions. Those three sessions' worth, nine evaluations, move forward, and the
# following week they may do more than three.
#
# One week, so the most anyone can carry is three sessions' worth. Missing four weeks
# does not entitle anyone to a thirty-nine competency session.
ROLLOVER_SESSIONS = 3


def sessions_missed_recently(attended_days, today=None, window=ROLLOVER_SESSIONS):
    """How many of the last `window` finished studio sessions the student missed.

    A rolling window, not a bank. Credit expires after a week, because Dave's framing is
    catching up *the following week*, and an unbounded balance would let someone save up
    all term and undo the spreading rule entirely.

    `attended_days` is the set of ISO dates they were present. Today's session does not
    count as missed until it is over.
    """
    today = today or today_toronto()
    finished = [day for day in studio_days() if day < today]
    return sum(1 for day in finished[-window:] if day.isoformat() not in attended_days)


def session_cap(base_cap, missed):
    """Their cap for this session, raised by the sessions they missed last week."""
    return base_cap + base_cap * min(missed, ROLLOVER_SESSIONS)


def session_cap_for(base_cap, attended_days, today=None):
    """The cap this student gets this session, given the days they were present."""
    return session_cap(base_cap, sessions_missed_recently(attended_days, today))


def session_signup_ok(course_counts, cap):
    counts = list(course_counts.values())
    if sum(counts) > cap:
        return False
    if counts and max(counts) - min(counts) > 1:
        return False
    return True


def covered_by(competency_id, edges):
    """Everything demonstrating this competency proves, following the chain (#80).

    `edges` maps a competency to the ones it DIRECTLY covers. The chain is followed
    because covering is transitive: if nested ifs proves simple ifs and simple ifs
    proves comparison operators, then nested ifs proves comparison operators. Storing
    only direct links keeps the map small and every row a judgement someone can
    actually make, and this is what makes that storage enough.

    Guards against cycles. Somebody will eventually write "X covers Y" and "Y covers
    X", which is wrong but easy to do halfway through a list of eighty, and without
    `seen` that pair is an infinite loop that hangs the marking screen mid-session.
    Here it just terminates.

    The starting competency is never in the result, even if a cycle leads back to it:
    demonstrating something does not credit it, marking it does.
    """
    seen = set()
    queue = list(edges.get(competency_id, ()))
    while queue:
        current = queue.pop()
        if current in seen or current == competency_id:
            continue
        seen.add(current)
        queue.extend(edges.get(current, ()))
    return seen


def sessions_for(courses, today=None):
    """(sessions_done, sessions_total) for a student taking exactly `courses` (#81).

    The denominator is the studio days that student was actually expected at, not the
    whole term. Somebody in CPS109 alone is due on Tuesdays and Thursdays, so their
    Wednesdays are not absences.

    A course we have no weekday map for contributes every studio weekday, which keeps
    an unrecognised course reporting the same denominator it did before this existed.

    Same "a session counts once it is over" rule as term_elapsed: the session a student
    is sitting in should not yet count against them.
    """
    today = today or today_toronto()
    weekdays = set()
    for course in courses:
        weekdays |= set(COURSE_WEEKDAYS.get(course, STUDIO_WEEKDAYS))
    if not weekdays:
        weekdays = set(STUDIO_WEEKDAYS)
    days = [day for day in studio_days() if day.weekday() in weekdays]
    return sum(1 for day in days if day < today), len(days)


# The share of their own sessions a student has to attend before the instructor's
# attendance penalty is in play (#108). Dave set this on July 15, and said in the same
# breath that he did not know exactly what "most of the classes" should mean before
# landing on half. A number arrived at that way should be movable without a deploy, so
# the real value is the `attendance_floor` setting and this is only the fallback.
ATTENDANCE_FLOOR = 0.5


def attendance_is_short(attended, due, floor=None):
    """Is this student below the attendance the instructor expects? (#108)

    The app never deducts anything for this. It marks who is below the line, and the
    instructor decides what that is worth, which is how Dave described it: a penalty he
    would apply to their remarks, not a formula.

    `due` of 0 means no session has finished yet, and nobody is behind on a term that
    has not started.
    """
    if not due:
        return False
    return attended < due * (ATTENDANCE_FLOOR if floor is None else floor)


def covers_label(count):
    """How to say that demonstrating this one also proves others (#110).

    The coverage map only ever lived in the database. A student had no way to know that
    one competency would earn them three, and a TA had no way to know a single tap was
    about to change three rows. Dave asked for this to save evaluation time, and it only
    does that if people can see which ones are worth picking.
    """
    if not count:
        return None
    return 'also proves ' + str(count) + (' other' if count == 1 else ' others')
