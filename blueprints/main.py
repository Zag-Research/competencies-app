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
    notice = session.pop('roster_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    with db.cursor() as sql:
        # Add a student who is not on the roster yet (#61). Sits at the top because the
        # moment it is needed is the moment someone cannot sign in and is standing there.
        f = form(method='post', action=url_for('main.add_student')).classes('add-student')
        f += input(type='text', name='student_number', placeholder='Student number')
        f += input(type='text', name='first_name', placeholder='First name')
        f += input(type='text', name='last_name', placeholder='Last name')
        for course in db.all_courses(sql):
            lbl = label().classes('queue-check')
            lbl += input(type='checkbox', name='courses', value=course)
            lbl += span(course)
            f += lbl
        f += button('Add student', type='submit').classes('roster-link')
        p += div(f).classes('add-student-wrap')
        for (number, first, last) in sql.execute(
                "select student_number, first_name, last_name from students order by last_name").fetchall():
            # one roster row per student: name plus a Mark and a View link
            p += div(
                span(last + ", " + first).classes('roster-name'),
                a('Mark', href=url_for('mark.mark_student', student_number=number)).classes('roster-link'),
                a('View', href=url_for('main.view_student', student_number=number)).classes('roster-link'),
            ).classes('roster-row')
    return str(p)


@main_bp.route('/students/add', methods=['POST'])
def add_student():
    """A TA adds a student who is not in the roster yet (#61).

    Students can add the course until the middle of September, so someone can turn up
    who was not on the class list when it was loaded. Without this they are stuck: the
    app does not recognise them, so they cannot sign up or be evaluated, and fixing it
    would need whoever has server access to run the importer.

    No delete counterpart, deliberately. A student who drops is marked by the importer,
    not removed, and a delete button beside student records is a bad idea in a room
    where people are working quickly.
    """
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    number = request.form.get('student_number', '').strip()
    first = request.form.get('first_name', '').strip()
    last = request.form.get('last_name', '').strip()
    courses = request.form.getlist('courses')
    if not (number and first and last and courses):
        session['roster_notice'] = ('Needs a student number, both names, and at least '
                                    'one course.')
        return redirect(url_for('main.index'))
    with db.cursor() as sql:
        db.add_or_update_student(sql, number, first, last, courses)
    session['roster_notice'] = first + ' ' + last + ' can sign in now.'
    return redirect(url_for('main.index'))


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
            filt = div().classes('subnav')
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
        # One bar, with a marker where the studio has got to. The studio figure is a
        # reference rather than a second thing to track, so it does not need a bar of
        # its own: the point is only to make the student's own number mean something,
        # since 30% says nothing until you know whether the term is 20% or 60% through.
        fill = div().classes('pace-fill')
        fill.addAttributes(style='width: ' + str(done_pct) + '%')
        track = div(fill).classes('pace-track')
        if elapsed:
            marker = div().classes('pace-marker')
            marker.addAttributes(style='left: ' + str(term_pct) + '%')
            track += marker
        pace = div().classes('pace')
        pace += div(
            track,
            span(str(done_pct) + '%').classes('pace-value'),
        ).classes('pace-row')
        pace += div(logic.pace_note(done_pct, term_pct, elapsed)).classes('pace-note')
        p += pace
        # Worth reading (#51). Sits directly under the pace bars, on purpose: the note
        # above may have just told them they are behind, and this is the nearest thing
        # to something to do about it. Only on a student's own page; staff have their
        # own view of this list.
        #
        # Dave asked for the newest three visible with older ones reachable, so every
        # link is rendered and the container scrolls, rather than the query being cut
        # to three and the rest becoming unreachable.
        if cur_role == 'student' and cur_user == student_number:
            reading = db.links_newest_first(sql)
            if reading:
                p += h2('Worth reading')
                box = div().classes('link-list')
                for (lid, title, why, _url) in reading:
                    item = div().classes('link-item')
                    # Through /link/<id> rather than straight out, so opening it is
                    # recorded. target=_blank keeps their progress page where it was.
                    item += a(title, href=url_for('main.open_link', link_id=lid),
                              target='_blank', rel='noopener noreferrer'
                              ).classes('link-title')
                    if why:
                        item += div(why).classes('link-why')
                    box += item
                p += box
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


@main_bp.route('/links')
def links():
    # Staff-only curation of the motivational reading (#51). Instructor-curated for
    # now, Dave's call; TAs and students only ever see the list, not this page.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    notice = session.pop('links_notice', None)
    p = page()
    p += page_header()
    p += h1('Worth reading')
    p += div('Shown on every student progress page, newest first.').classes('subnav')
    if notice:
        p += div(notice).classes('queue-notice')
    with db.cursor() as sql:
        rows = db.links_newest_first(sql)
        engagement = db.link_engagement(sql)
        unread = db.students_with_no_clicks(sql)
        total_students = sql.execute('select count(*) from students').fetchone()[0]
    f = form(method='post', action=url_for('main.add_link')).classes('link-add')
    f += input(type='text', name='title', placeholder='Title', required=True)
    f += input(type='text', name='why', placeholder='Why this is worth 5 minutes')
    f += input(type='url', name='url', placeholder='https://...', required=True)
    f += button('Add', type='submit').classes('roster-link')
    p += f
    p += h2('Current list')
    if not rows:
        p += div('Nothing added yet.').classes('queue-empty')
    for (lid, title, why, url) in rows:
        opened = engagement.get(lid, 0)
        row = div().classes('progress-row')
        row += span(title).classes('progress-name')
        row += span(str(opened) + ' of ' + str(total_students) + ' opened it'
                    ).classes('progress-badge')
        drop = form(method='post', action=url_for('main.delete_link', link_id=lid))
        drop += button('Remove', type='submit').classes('roster-link')
        row += drop
        p += row
        if why:
            p += div(why).classes('link-why')
    # The list that makes the click tracking worth having: Dave wanted it "per student
    # so we can encourage students to stay engaged", and this is who to encourage.
    if rows:
        p += h2('Has not opened anything')
        if not unread:
            p += div('Everyone has opened at least one. Unusual and good.'
                     ).classes('queue-empty')
        for (first, last, _number) in unread:
            p += div(span(last + ', ' + first).classes('progress-name')
                     ).classes('progress-row')
    return str(p)


@main_bp.route('/links/add', methods=['POST'])
def add_link():
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    title = request.form.get('title', '').strip()
    why = request.form.get('why', '').strip()
    url = request.form.get('url', '').strip()
    # Only http(s). The list is instructor-curated, but this page writes a URL the app
    # later redirects students to, so the scheme is worth pinning down here rather than
    # trusting a paste.
    if not title or not url.lower().startswith(('http://', 'https://')):
        session['links_notice'] = 'Needs a title and an http(s) link.'
        return redirect(url_for('main.links'))
    with db.cursor() as sql:
        db.add_link(sql, title, why, url)
    return redirect(url_for('main.links'))


@main_bp.route('/links/<int:link_id>/delete', methods=['POST'])
def delete_link(link_id):
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        db.remove_link(sql, link_id)
    return redirect(url_for('main.links'))


@main_bp.route('/link/<int:link_id>')
def open_link(link_id):
    """Record that this student opened a link, then send them to it (#51).

    The click is the whole reason this hop exists rather than linking straight out:
    Dave was doubtful students would read any of this, and per-student clicks are what
    answer that rather than leaving it a guess.
    """
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        target = db.link_url(sql, link_id)
        if target is None:
            return redirect(url_for('main.index'))
        # Staff previewing the list are not students engaging with it, so their clicks
        # would only dilute the numbers this page exists to produce.
        if role == 'student':
            db.record_link_click(sql, user, link_id)
    return redirect(target)


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
    p += div('Passed and not passed count the same.').classes('subnav')
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
