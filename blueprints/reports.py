"""Staff-facing reports: aggregate numbers the instructor and TAs read.

Separate from main.py deliberately (#74). These are all "look at everyone at once"
pages rather than anything a student touches, and main.py had already become
everything that was not the queue.
"""
from flask import Blueprint, url_for, redirect, request
from myhtml import *
import db
import logic
from common import current_user, page_header

reports_bp = Blueprint('reports', __name__)

# What the competencies are worth in total (#22). Dave's design is that passing all of
# them puts a student at roughly 80%, and the rest comes from his remarks.
#
# A share PER competency was hardcoded here at 2%, which is only correct while a course
# has exactly 40 of them (#98). The list is not final, and one added or retired
# competency would have quietly made a perfect student read 82% or 78%. Derived from the
# count instead, so the list can change and this number stays honest.
COMPETENCIES_ARE_WORTH = 80


def _due_sessions_cache():
    """sessions_for is the same answer for every student taking the same courses.

    There are two courses, so at most a handful of distinct answers across 45 students,
    against studio_days() walking the whole term each time. Cached per call of the page.
    """
    cache = {}

    def due(courses):
        if courses not in cache:
            cache[courses] = logic.sessions_for(courses)[0]
        return cache[courses]
    return due


@reports_bp.route('/progress')
def progress():
    """Everyone's progress, per course, on one page.

    Two uses, which is why the order can be switched. During term it answers "who
    should a TA go and encourage", which wants the furthest behind first. At the end
    it answers "what do I type into D2L", which wants surname order to read straight
    across (#72).

    Deliberately does not compute a final grade. Dave's model is the competencies plus
    adjustments he makes by judgement: shout-outs, attendance, projects. The app should
    show him the inputs, not produce a number he then has to argue with.
    """
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    order = 'name' if request.args.get('order') == 'name' else 'behind'
    p = page()
    p += page_header()
    p += h1('Progress')
    nav = div().classes('subnav')
    for (key, text) in (('behind', 'Furthest behind'), ('name', 'By name')):
        link = a(text, href=url_for('reports.progress', order=key)).classes('queue-toggle')
        if key == order:
            link.addClasses('is-active')
        nav += link
    p += nav
    with db.cursor() as sql:
        rows = db.progress_by_student(sql)
        # Excluding today, to match the denominator (#89): both sides count only
        # sessions that are over, or a student present right now reads as n of n-1.
        attended = {number: n for (number, _f, _l, n) in
                    db.attendance_counts(sql, before=logic.today_toronto().isoformat())}
        thanked = {number: people
                   for (number, _f, _l, _n, people) in db.endorsement_tallies(sql)}
        elapsed, _total = logic.term_elapsed()
    if not rows:
        p += div('No students loaded yet.').classes('queue-empty')
        return str(p)

    def overall(row):
        (_last, _first, _number, courses) = row
        done = sum(n for (_c, n, _t) in courses)
        total = sum(t for (_c, _n, t) in courses)
        return done / total if total else 0

    rows.sort(key=lambda r: (r[0], r[1]) if order == 'name' else (overall(r), r[0]))

    due_sessions = _due_sessions_cache()
    for (last, first, number, courses) in rows:
        row = div().classes('progress-row')
        row += span(last + ', ' + first).classes('progress-name')
        for (course, done, total) in courses:
            share = logic.percent(done * COMPETENCIES_ARE_WORTH, total * 100) if total else 0
            row += span(course + ' ' + str(share) + '%'
                        ).classes('progress-badge').addClasses(
                            'state-achieved' if done else 'state-unassessed')
        # The two things that feed Dave's remarks, next to the competencies rather than
        # folded into them, because how they count is his call not the app's.
        here = attended.get(number, 0)
        # Against the sessions THIS student was due at, not the whole term (#81).
        # CPS109 meets Tuesday and Thursday, CPS213 Tuesday and Wednesday, so someone
        # in one course alone has no business being counted absent on the day their
        # course does not run. The flag below feeds the attendance penalty, so getting
        # the denominator wrong is a mark against somebody who came to everything.
        due = due_sessions(tuple(course for (course, _d, _t) in courses))
        if due:
            attend = span(str(here) + ' of ' + str(due)).classes('progress-badge')
            if here * 2 < due:
                attend.addClasses('state-cooling_off')
            row += attend
        helped = thanked.get(number, 0)
        if helped:
            row += span('thanked by ' + str(helped)).classes('progress-badge')
        p += row
    return str(p)
