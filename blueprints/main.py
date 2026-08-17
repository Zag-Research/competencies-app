"""The roster home page and the read-only student progress view."""
from flask import Blueprint, url_for, redirect, request, session
from myhtml import *
import db
import logic
from common import current_user, page_header

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
    # (Queue / Attendance / Shout-outs live in the header nav now, no second row here.)
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
    cur_user, cur_role = current_user()
    if cur_user is None:
        return redirect(url_for('auth.login'))
    # A student may only see their own progress, not a classmate's grades. Staff
    # (who mark and coach) can view anyone.
    if cur_role == 'student' and cur_user != student_number:
        return redirect(url_for('main.view_student', student_number=cur_user))
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
        # Staff reach the roster from the header nav now; a student gets a sign-up link.
        nav = div().classes('subnav')
        if cur_role == 'student' and cur_user == student_number:
            nav += a('Sign up to be evaluated →', href=url_for('queue.queue'))
        p += nav
        states, recorded_at = db.achievement_states(sql, student_number)
        # Competencies currently in the queue, so the progress page can show "in the
        # queue" / "carried over" instead of a bare "not assessed".
        pending = db.pending_competencies(sql, student_number)
        # Only this student's enrolled courses (#11): a part-time student in CPS109
        # sees 40 competencies, not all 80.
        comps = db.competencies_for(sql, student_number)
        # Optional filter to one course, offered only when they take more than one.
        courses_here = list(dict.fromkeys(c for (_cid, _name, c) in comps))
        selected = request.args.get('course')
        if selected not in courses_here:
            selected = None
        if len(courses_here) > 1:
            filt = div(span('Show ')).classes('subnav')
            alllink = a('All', href=url_for('main.view_student',
                                            student_number=student_number)).classes('queue-toggle')
            if selected is None:
                alllink.addClasses('is-active')
            filt += alllink
            for c in courses_here:
                link = a(c, href=url_for('main.view_student',
                                         student_number=student_number, course=c)).classes('queue-toggle')
                if selected == c:
                    link.addClasses('is-active')
                filt += link
            p += filt
        # Pace (#50): the student's completion against the studio's, so drifting
        # behind shows up in week 4 rather than week 11. Counted over whatever the
        # filter above is showing, so narrowing to one course narrows the figure
        # with it and the number always describes the list underneath it.
        shown = [cid for (cid, _name, course) in comps
                 if not selected or course == selected]
        achieved = sum(1 for cid in shown if states.get(cid) == 'achieved')
        elapsed, sessions = logic.term_elapsed()
        done_pct = logic.percent(achieved, len(shown))
        term_pct = logic.percent(elapsed, sessions)
        pace = div().classes('pace')
        for label, pct, tone in (('Competencies', done_pct, 'is-you'),
                                 ('Studio', term_pct, 'is-term')):
            fill = div().classes('pace-fill').addClasses(tone)
            fill.addAttributes(style='width: ' + str(pct) + '%')
            pace += div(
                span(label).classes('pace-label'),
                div(fill).classes('pace-track'),
                span(str(pct) + '%').classes('pace-value'),
            ).classes('pace-row')
        pace += div(logic.pace_note(done_pct, term_pct, elapsed)).classes('pace-note')
        p += pace
        current_course = None
        for (cid, name, course) in comps:
            if selected and course != selected:
                continue
            # One heading per course as the list crosses from CPS109 into CPS213,
            # so the combined list stays readable.
            if course != current_course:
                p += h2(course or 'Other')
                current_course = course
            # A queued competency shows its queue status; otherwise its recorded state.
            if cid in pending:
                badge = pending[cid]  # 'carried_over' or 'in_queue'
                state_label = 'Carried over' if badge == 'carried_over' else 'In the queue'
            else:
                badge = logic.achievement_state(cid, states)
                if badge == 'cooling_off':
                    state_label = logic.cooling_off_label(recorded_at.get(cid))
                else:
                    state_label = logic.STATE_LABELS[badge]
            p += div(
                span(name).classes('progress-name'),
                span(state_label).classes('progress-badge').addClasses('state-' + badge),
            ).classes('progress-row')
        # Only the student themselves, looking at their own page, can thank a
        # classmate. Staff viewing this page (via "View") do not see the control.
        if cur_role == 'student' and cur_user == student_number:
            mates = db.classmates(sql, student_number)
            given = db.endorsements_given_today(
                sql, student_number, logic.today_toronto().isoformat())
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
        added = db.add_endorsement(
            sql, user, to_student, logic.today_toronto().isoformat())
    name = who[0] + ' ' + who[1]
    session['endorse_notice'] = (
        'Thanks sent to ' + name + '.' if added
        else 'You already thanked ' + name + ' today.'
    )
    return redirect(url_for('main.view_student', student_number=user))


@main_bp.route('/evaluators')
def evaluators():
    # Staff-only. Who has recorded each evaluation, so the instructor can spot
    # someone carrying too little and encourage them, rather than finding out at
    # the end of term (#49). Framed the way it was raised in the Aug 12 meeting:
    # about sharing the load, not ranking people. Students never see this.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    p = page()
    p += page_header()
    p += h1('Evaluations by evaluator')
    p += div('Every evaluation counts the same here, passed or not, because both '
             'take the same time at the desk. A retry counts for both TAs: the one '
             'who said "not yet" did the work as much as the one who passed them. '
             'The recent column is the last seven days.').classes('subnav')
    with db.cursor() as sql:
        total = db.evaluator_counts(sql)
        recent = db.evaluator_counts(sql, since=logic.days_ago(7))
    if not total:
        p += div('No evaluations recorded yet.').classes('queue-empty')
        return str(p)
    for who in sorted(total, key=lambda w: -total[w]):
        p += div(
            span(who).classes('progress-name'),
            span(str(recent.get(who, 0)) + ' in the last 7 days').classes('progress-badge'),
            span(str(total[who]) + ' total').classes('progress-badge'),
        ).classes('progress-row')
    return str(p)


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
