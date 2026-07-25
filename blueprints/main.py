"""The roster home page and the read-only student progress view."""
from flask import Blueprint, url_for, redirect, request, session
from myhtml import *
import db
import logic
from common import current_user, userCas, page_header

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if role == 'student':
        return redirect(url_for('main.view_student', student_number=user))
    p = page()
    p += page_header()
    p += h1('Students')
    p += div(
        a('Queue →', href=url_for('queue.queue')),
        a('Attendance →', href=url_for('main.attendance')),
        a('Shout-outs →', href=url_for('main.endorsements')),
    ).classes('subnav')
    with db.cursor() as sql:
        for (number, first, last) in sql.execute(
                "select student_number, first_name, last_name from students order by last_name").fetchall():
            # one roster row per student: name plus a Mark and a View link
            p += div(
                span(last + ", " + first).classes('roster-name'),
                a('Mark', href=url_for('mark.mark_student', student_number=number)).classes('roster-link'),
                a('View', href=url_for('main.view_student', student_number=number)).classes('roster-link'),
            ).classes('roster-row')
    return str(p)


@main_bp.route('/view/<student_number>')
def view_student(student_number=None):
    user, casUser = userCas()
    # One-shot notice from a just-submitted thank-you (set by endorse()).
    endorse_notice = session.pop('endorse_notice', None)
    p = page()
    p += page_header()
    with db.cursor() as sql:
        student = sql.execute(
            "select first_name, last_name from students where student_number = ?",
            (student_number,)
        ).fetchone()
        if student is None:
            p += h1('Student not found')
            return str(p)
        first, last = student
        p += h1('Progress: ' + first + ' ' + last)
        cur_user, cur_role = current_user()
        nav = div().classes('subnav')
        nav += a('← Back to students', href=url_for('main.index')).classes('back-link')
        if cur_role == 'student' and cur_user == student_number:
            nav += a('Join queue →', href=url_for('queue.queue'))
        p += nav
        states = {}
        recorded_at = {}
        for (cid, status, recorded) in sql.execute(
            "select competency_id, status, date_recorded from achievements where student_number = ?",
            (student_number,)
        ).fetchall():
            states[cid] = status
            recorded_at[cid] = recorded
        current_course = None
        for (cid, name, course) in sql.execute(
            "select id, name, course from competencies order by id"
        ).fetchall():
            # One heading per course as the list crosses from CPS109 into CPS213,
            # so the combined 80-competency list stays readable.
            if course != current_course:
                p += h2(course or 'Other')
                current_course = course
            state = logic.achievement_state(cid, states)
            if state == 'cooling_off':
                state_label = logic.cooling_off_label(recorded_at.get(cid))
            else:
                state_label = logic.STATE_LABELS[state]
            p += div(
                span(name).classes('progress-name'),
                span(state_label).classes('progress-badge').addClasses('state-' + state),
            ).classes('progress-row')
        # Only the student themselves, looking at their own page, can thank a
        # classmate. Staff viewing this page (via "View") do not see the control.
        if cur_role == 'student' and cur_user == student_number:
            mates = db.classmates(sql, student_number)
            given = db.endorsements_given_today(sql, student_number)
            p += h2('Thank a classmate')
            p += div('Someone help you today? Give them a shout-out. It counts '
                     'toward their mark. One per classmate per day.').classes('subnav')
            if endorse_notice:
                p += div(endorse_notice).classes('queue-notice')
            if mates:
                f = form(method='post', action=url_for('main.endorse'))
                sel = select(name='to_student').classes('endorse-select')
                # Empty first option so nothing is thanked by an accidental submit.
                sel += option('Choose a classmate…', value='')
                for (num, fn, ln) in mates:
                    sel += option(ln + ', ' + fn, value=num)
                f += sel
                f += button('Send thanks', type='submit').classes('roster-link')
                p += f
            if given:
                names = ', '.join(fn + ' ' + ln for (fn, ln) in given)
                p += div('You thanked today: ' + names).classes('endorse-given')
    return str(p)


@main_bp.route('/endorse', methods=['POST'])
def endorse():
    # A student thanks a classmate who helped them. Redirects back to their own
    # progress page with a one-shot confirmation.
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    to_student = request.form.get('to_student', '').strip()
    with db.cursor() as sql:
        who = sql.execute(
            "select first_name, last_name from students where student_number = ?",
            (to_student,)
        ).fetchone() if to_student else None
        if who is None or to_student == user:
            # Empty pick, unknown number, or their own name: nothing recorded.
            session['endorse_notice'] = 'Pick a classmate from the list.'
            return redirect(url_for('main.view_student', student_number=user))
        added = db.add_endorsement(sql, user, to_student)
    name = who[0] + ' ' + who[1]
    session['endorse_notice'] = (
        'Thanks sent to ' + name + '.' if added
        else 'You already thanked ' + name + ' today.'
    )
    return redirect(url_for('main.view_student', student_number=user))


@main_bp.route('/attendance')
def attendance():
    # Staff-only. Two things: how many sessions each student has attended (the raw
    # signal for the miss-more-than-half rule), and who was present on a given day.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    day = request.args.get('day')
    if not logic.is_studio_day(day or ''):
        day = logic.today_toronto().isoformat()
    p = page()
    p += page_header()
    p += h1('Attendance')
    p += div(a('← Back to students', href=url_for('main.index'))).classes('subnav')
    p += div('Sessions attended per student. The attended-vs-total percentage '
             'arrives with the term calendar at deployment; for now this is the '
             'raw count.').classes('subnav')
    with db.cursor() as sql:
        counts = db.attendance_counts(sql)
        roster = db.attendance_for_day(sql, day)
    p += h2('Sessions attended')
    if not counts:
        p += div('No check-ins yet.').classes('queue-empty')
    else:
        for (fn, ln, n) in counts:
            p += div(
                span(ln + ', ' + fn).classes('progress-name'),
                span(str(n) + (' session' if n == 1 else ' sessions')
                     ).classes('progress-badge'),
            ).classes('progress-row')
    # Who was present on one specific session.
    heading = logic.studio_label(day)
    if day == logic.today_toronto().isoformat():
        heading += ' (today)'
    p += h2('Present on ' + heading)
    if not roster:
        p += div('Nobody checked in for this session.').classes('queue-empty')
    else:
        for (fn, ln) in roster:
            p += div(span(ln + ', ' + fn).classes('progress-name')).classes('progress-row')
    return str(p)


@main_bp.route('/endorsements')
def endorsements():
    # Staff-only tally of who has been thanked, most first, for course remarks.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    p = page()
    p += page_header()
    p += h1('Peer shout-outs')
    p += div(a('← Back to students', href=url_for('main.index'))).classes('subnav')
    with db.cursor() as sql:
        tallies = db.endorsement_tallies(sql)
    if not tallies:
        p += div('No shout-outs yet.').classes('queue-empty')
        return str(p)
    for (fn, ln, n) in tallies:
        p += div(
            span(ln + ', ' + fn).classes('progress-name'),
            span(str(n) + (' shout-out' if n == 1 else ' shout-outs')
                 ).classes('progress-badge'),
        ).classes('progress-row')
    return str(p)
