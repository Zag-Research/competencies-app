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

# Each competency is worth 2% of the course (#22), so 40 of them is the 80% Dave
# describes as the ceiling before remarks.
PERCENT_PER_COMPETENCY = 2


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
        attended = {number: n for (number, _f, _l, n) in db.attendance_counts(sql)}
        thanked = {number: people
                   for (number, _f, _l, _n, people) in db.endorsement_tallies(sql)}
        elapsed, _total = logic.term_elapsed()
        course_count = len(db.all_courses(sql))
    if not rows:
        p += div('No students loaded yet.').classes('queue-empty')
        return str(p)

    def overall(row):
        (_last, _first, _number, courses) = row
        done = sum(n for (_c, n, _t) in courses)
        total = sum(t for (_c, _n, t) in courses)
        return done / total if total else 0

    rows.sort(key=lambda r: (r[0], r[1]) if order == 'name' else (overall(r), r[0]))

    for (last, first, number, courses) in rows:
        row = div().classes('progress-row')
        row += span(last + ', ' + first).classes('progress-name')
        for (course, done, total) in courses:
            row += span(course + ' ' + str(done * PERCENT_PER_COMPETENCY) + '%'
                        ).classes('progress-badge').addClasses(
                            'state-achieved' if done else 'state-unassessed')
        # The two things that feed Dave's remarks, next to the competencies rather than
        # folded into them, because how they count is his call not the app's.
        here = attended.get(number, 0)
        if course_count and len(courses) < course_count:
            # A student in only one of the two courses is not registered for every
            # session, and nothing in the app records which ones they are meant to be
            # at (#81). Measured against the whole term they look absent for sessions
            # they were never in, and the under-half flag feeds the attendance penalty,
            # so this would mark down someone who came to everything they signed up
            # for. Show what is known, the count, and assert no ratio. It becomes a
            # real fraction once the timetable exists.
            row += span(str(here) + (' session' if here == 1 else ' sessions')
                        ).classes('progress-badge')
        elif elapsed:
            attend = span(str(here) + ' of ' + str(elapsed)).classes('progress-badge')
            if here * 2 < elapsed:
                attend.addClasses('state-cooling_off')
            row += attend
        helped = thanked.get(number, 0)
        if helped:
            row += span('thanked by ' + str(helped)).classes('progress-badge')
        p += row
    return str(p)
