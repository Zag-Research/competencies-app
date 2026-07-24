"""The evaluation queue: student sign-up and the staff who's-next / marking view."""
from flask import Blueprint, request, url_for, session, redirect
from myhtml import *
import db
import logic
from common import current_user, page_header

queue_bp = Blueprint('queue', __name__)


def queue_student_view(student_number):
    p = page()
    p += page_header()
    p += h1('Evaluation queue')
    p += div(a('← My progress', href=url_for('main.view_student', student_number=student_number))).classes('subnav')
    # One-shot notice (e.g. hit the daily cap), set on the previous POST.
    notice = session.pop('queue_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    with db.cursor() as sql:
        states = {}
        recorded_at = {}
        for (cid, status, recorded) in sql.execute(
            "select competency_id, status, date_recorded from achievements where student_number = ?",
            (student_number,)
        ).fetchall():
            states[cid] = status
            recorded_at[cid] = recorded
        # 'claimed' as well as 'waiting': a TA taking the student must not make their
        # own queue page go blank. They still have those requests open, and someone
        # is on the way.
        pending = sql.execute(
            """select r.id, r.competency_id, c.name, r.seat, r.status from requests r
               join competencies c on r.competency_id = c.id
               where r.student_number = ? and r.status in ('waiting', 'claimed')
               order by r.requested_at""",
            (student_number,)
        ).fetchall()
        pending_ids = {row[1] for row in pending}
        # One seat per student: whatever their open requests say they are sitting at.
        seat = next((row[3] for row in pending if row[3]), None)
        being_evaluated = any(row[4] == 'claimed' for row in pending)
        all_competencies = sql.execute(
            "select id, name, course from competencies order by id"
        ).fetchall()
        remaining_today = db.daily_cap() - db.requests_used_today(sql, student_number)
    available = []
    for (cid, name, course) in all_competencies:
        if cid in pending_ids:
            continue
        state = states.get(cid, 'unassessed')
        if state == 'unassessed':
            available.append((cid, name, course))
        elif state == 'cooling_off':
            # A cooling-off competency reappears in the sign-up list only once its
            # two-day retry window has passed.
            if logic.retry_available(recorded_at.get(cid)):
                available.append((cid, name, course))
    if pending:
        p += h2('In the queue')
        # Students sign up before they get to the lab, so a request starts with no
        # seat. Until they enter one, staff cannot see them: there is nowhere to
        # walk to. Entering a seat is what puts them in front of a TA.
        if being_evaluated:
            p += div('A TA is on their way to you.').classes('queue-seat-set')
        elif seat:
            p += div(
                span('You are at seat ' + seat + '. A TA will come to you.'),
            ).classes('queue-seat-set')
        else:
            p += div('You are signed up. Enter your seat number when you get to '
                     'the lab, so a TA can find you. You will not appear in the '
                     'staff queue until you do.').classes('queue-notice')
        f = form(method='post', action=url_for('queue.queue_seat'))
        f += span('Seat number' if not seat else 'Moved machines?')
        f += input(type='text', name='seat', value=seat or '', placeholder='e.g. 12')
        f += button('I am here' if not seat else 'Update seat',
                    type='submit').classes('roster-link')
        p += div(f).classes('queue-seat')
        for (rid, _cid, name, _seat, status) in pending:
            row = div(span(name).classes('progress-name')).classes('queue-row')
            if status == 'claimed':
                # A TA is already standing up to come over. Cancelling now would
                # pull the student out from under them.
                row += span('being evaluated').classes('queue-card-seat')
            else:
                row += form(
                    button('Cancel', type='submit').classes('roster-link'),
                    method='post',
                    action=url_for('queue.queue_cancel', request_id=rid)
                )
            p += row
        if seat:
            # Leaving clears the seat, which drops them out of the staff queue
            # without cancelling what they signed up for.
            p += form(
                button('I have left the lab', type='submit').classes('roster-link'),
                method='post',
                action=url_for('queue.queue_seat')
            ).classes('queue-release')
    if available and remaining_today > 0:
        p += h2('Sign up')
        p += div(str(remaining_today) + ' of ' + str(db.daily_cap())
                 + ' requests left today.').classes('queue-allowance')
        f = form(method='post', action=url_for('queue.queue_join'))
        current_course = None
        for (cid, name, course) in available:
            # Sub-heading each time the available list crosses into another course.
            if course != current_course:
                f += div(course or 'Other').classes('queue-course')
                current_course = course
            lbl = label().classes('queue-check')
            lbl += input(type='checkbox', name='competency_ids', value=str(cid))
            lbl += span(name)
            f += lbl
        f += button('Join queue', type='submit').classes('roster-link')
        p += f
    elif available and remaining_today <= 0:
        p += div('You have used all ' + str(db.daily_cap())
                 + ' of today\'s requests.').classes('queue-empty')
    elif not pending:
        p += div('Nothing to sign up for right now.').classes('queue-empty')
    return str(p)


def queue_staff_view(group_by='student'):
    p = page()
    p += page_header()
    p += h1('Evaluation queue')
    nav = div(a('← Back to students', href=url_for('main.index'))).classes('subnav')
    # Same requests, two groupings: work through one student at a time, or work
    # through everyone who wants the same competency.
    for (key, text) in (('student', 'By student'), ('competency', 'By competency')):
        link = a(text, href=url_for('queue.queue', group=key)).classes('queue-toggle')
        if key == group_by:
            link.addClasses('is-active')
        nav += link
    p += nav
    # One-shot notice, e.g. losing a race to claim a student, or releasing one.
    notice = session.pop('queue_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    with db.cursor() as sql:
        rows = sql.execute(
            """select r.student_number, s.first_name, s.last_name,
                      r.competency_id, c.name, r.seat
                 from requests r
                 join students s on r.student_number = s.student_number
                 join competencies c on r.competency_id = c.id
                where """ + db.AVAILABLE + """
                order by r.requested_at""",
            (db.claim_cutoff(),)
        ).fetchall()
    if not rows:
        p += div('Queue is empty.').classes('queue-empty')
        return str(p)
    if group_by == 'competency':
        p += queue_by_competency(rows)
    else:
        p += queue_by_student(rows)
    return str(p)


def queue_by_student(rows):
    # Group the flat rows by student so each student shows once, with all their
    # requested competencies listed under them. Insertion order (Python dict)
    # preserves the requested_at ordering from the query, so the student who has
    # waited longest stays at the top.
    students = {}
    for (number, first, last, _cid, comp_name, seat) in rows:
        if number not in students:
            students[number] = {'name': last + ', ' + first, 'seat': seat, 'items': []}
        students[number]['items'].append(comp_name)
    out = div()
    for (number, group) in students.items():
        # The whole card is one button: claiming the student and opening their
        # evaluation screen is a single action, so no TA can walk over to a student
        # without first taking them out of everyone else's queue.
        card = form(method='post',
                    action=url_for('queue.queue_claim', student_number=number))
        b = button(type='submit').classes('queue-card', 'queue-claim')
        b += div(
            span(group['name']).classes('queue-card-name'),
            span('seat ' + group['seat']).classes('queue-card-seat'),
        ).classes('queue-card-head')
        for comp_name in group['items']:
            b += div(span(comp_name).classes('progress-name')).classes('queue-row')
        card += b
        out += card
    return out


def queue_by_competency(rows):
    # Same rows, grouped the other way: one card per competency, listing everyone
    # waiting on it, so a TA can evaluate the whole cohort in one pass instead of
    # repeating the same evaluation student by student.
    comps = {}
    for (_number, first, last, cid, comp_name, seat) in rows:
        if cid not in comps:
            comps[cid] = {'name': comp_name, 'students': []}
        comps[cid]['students'].append((last + ', ' + first, seat))
    out = div()
    for (cid, group) in comps.items():
        card = form(method='post',
                    action=url_for('queue.queue_claim_group', competency_id=cid))
        b = button(type='submit').classes('queue-card', 'queue-claim')
        count = len(group['students'])
        b += div(
            span(group['name']).classes('queue-card-name'),
            span(str(count) + (' student' if count == 1 else ' students')
                 ).classes('queue-card-seat'),
        ).classes('queue-card-head')
        for (name, seat) in group['students']:
            b += div(
                span(name).classes('progress-name'),
                span('seat ' + seat).classes('queue-card-seat'),
            ).classes('queue-row')
        card += b
        out += card
    return out


def queue_cohort_view(competency_id, evaluator):
    """The claimed cohort: everyone this TA took for one competency, marked together."""
    p = page()
    p += page_header()
    undo = session.pop('queue_undo', None)
    with db.cursor() as sql:
        comp = sql.execute(
            "select name from competencies where id = ?", (competency_id,)
        ).fetchone()
        if comp is None:
            p += h1('Competency not found')
            return str(p)
        rows = sql.execute(
            """select r.id, r.student_number, s.first_name, s.last_name, r.seat
                 from requests r
                 join students s on r.student_number = s.student_number
                where r.competency_id = ? and r.status = 'claimed'
                  and r.claimed_by = ?
                order by r.requested_at""",
            (competency_id, evaluator)
        ).fetchall()
        undo_row = None
        if undo:
            undo_row = sql.execute(
                """select s.first_name, s.last_name from requests r
                   join students s on r.student_number = s.student_number
                   where r.id = ?""",
                (undo['rid'],)
            ).fetchone()
    p += h1('Evaluating: ' + comp[0])
    p += div(a('← Back to queue',
               href=url_for('queue.queue', group='competency'))).classes('subnav')
    notice = session.pop('queue_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    if undo_row:
        outcome = 'Achieved' if undo['state'] == 'achieved' else 'Not passed'
        banner = div().classes('queue-notice')
        banner += span('Marked ' + undo_row[0] + ' ' + undo_row[1]
                       + ' as ' + outcome + '.')
        banner += form(
            button('Undo', type='submit').classes('roster-link'),
            method='post',
            action=url_for('queue.queue_undo', request_id=undo['rid'],
                           back='competency')
        )
        p += banner
    if not rows:
        p += div('Nobody left to evaluate for this competency.').classes('queue-empty')
        p += div(a('← Back to queue', href=url_for('queue.queue', group='competency')
                   ).classes('roster-link')).classes('subnav')
        return str(p)
    for (rid, student_number, first, last, seat) in rows:
        actions = div().classes('queue-actions')
        actions += form(
            button('Achieved', type='submit').classes('roster-link', 'queue-yes'),
            method='post',
            action=url_for('queue.queue_mark', request_id=rid, state='achieved',
                           back='competency')
        )
        actions += form(
            button('Not passed', type='submit').classes('roster-link', 'queue-no'),
            method='post',
            action=url_for('queue.queue_mark', request_id=rid, state='cooling_off',
                           back='competency')
        )
        # Claiming the cohort claimed each student whole, so this TA also holds
        # whatever else they asked for. Link through so it can be marked in the
        # same visit rather than making the student rejoin the queue.
        who = div(
            a(last + ', ' + first,
              href=url_for('queue.queue_evaluate', student_number=student_number)
              ).classes('progress-name'),
            span('seat ' + seat).classes('queue-card-seat'),
        ).classes('queue-cohort-who')
        p += div(who, actions).classes('queue-row')
    p += form(
        button('Release remaining back to queue', type='submit').classes('roster-link'),
        method='post',
        action=url_for('queue.queue_release_group', competency_id=competency_id)
    ).classes('queue-release')
    return str(p)


def queue_evaluate_view(student_number, evaluator):
    """The claimed student's evaluation screen: only what they asked for today."""
    p = page()
    p += page_header()
    # One-shot "you just marked X — Undo" banner, set by queue_mark.
    undo = session.pop('queue_undo', None)
    with db.cursor() as sql:
        student = sql.execute(
            "select first_name, last_name from students where student_number = ?",
            (student_number,)
        ).fetchone()
        if student is None:
            p += h1('Student not found')
            return str(p)
        first, last = student
        # Only this evaluator's own claims. If their claim went stale and someone
        # else took the student, this comes back empty and they are told so.
        rows = sql.execute(
            """select r.id, c.name, r.seat
                 from requests r
                 join competencies c on r.competency_id = c.id
                where r.student_number = ? and r.status = 'claimed'
                  and r.claimed_by = ?
                order by r.requested_at""",
            (student_number, evaluator)
        ).fetchall()
        undo_row = None
        if undo:
            undo_row = sql.execute(
                "select c.name from requests r join competencies c"
                " on r.competency_id = c.id where r.id = ?",
                (undo['rid'],)
            ).fetchone()
    p += h1('Evaluating: ' + first + ' ' + last)
    seat = rows[0][2] if rows else None
    subnav = div(a('← Back to queue', href=url_for('queue.queue'))).classes('subnav')
    if seat:
        subnav += span('seat ' + seat).classes('queue-card-seat')
    p += subnav
    # One-shot notice, e.g. confirming a competency was handed back to the queue.
    notice = session.pop('queue_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    if undo_row:
        outcome = 'Achieved' if undo['state'] == 'achieved' else 'Not passed'
        banner = div().classes('queue-notice')
        banner += span('Marked ' + undo_row[0] + ' as ' + outcome + '.')
        banner += form(
            button('Undo', type='submit').classes('roster-link'),
            method='post',
            action=url_for('queue.queue_undo', request_id=undo['rid'])
        )
        p += banner
    if not rows:
        # Either every request is marked, or the claim expired and another TA took
        # them. Either way there is nothing left for this evaluator to do here.
        p += div('Nothing left to evaluate for this student.').classes('queue-empty')
        p += div(a('← Back to queue',
                   href=url_for('queue.queue')).classes('roster-link')).classes('subnav')
        return str(p)
    for (rid, comp_name, _seat) in rows:
        # Two one-tap outcomes per competency; each records the result and clears
        # the request at once.
        actions = div().classes('queue-actions')
        actions += form(
            button('Achieved', type='submit').classes('roster-link', 'queue-yes'),
            method='post',
            action=url_for('queue.queue_mark', request_id=rid, state='achieved')
        )
        actions += form(
            button('Not passed', type='submit').classes('roster-link', 'queue-no'),
            method='post',
            action=url_for('queue.queue_mark', request_id=rid, state='cooling_off')
        )
        # Third option, and NOT an outcome: the TA cannot assess this one today.
        # It goes back on the list for another evaluator instead of being guessed
        # at. Works both before starting (tap it the moment the screen opens) and
        # partway through, which is why there is only one button for both.
        actions += form(
            button("Can't evaluate", type='submit').classes('roster-link', 'queue-defer'),
            method='post',
            action=url_for('queue.queue_decline', request_id=rid)
        )
        p += div(
            span(comp_name).classes('progress-name'),
            actions,
        ).classes('queue-row')
    # Backing out has to be possible, or a TA who claims by mistake strands the
    # student where no other TA can see them.
    p += form(
        button('Release back to queue', type='submit').classes('roster-link'),
        method='post',
        action=url_for('queue.queue_release', student_number=student_number)
    ).classes('queue-release')
    return str(p)


@queue_bp.route('/queue')
def queue():
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if role == 'student':
        return queue_student_view(user)
    if role == 'staff':
        group = request.args.get('group')
        return queue_staff_view('competency' if group == 'competency' else 'student')
    return redirect(url_for('auth.login'))


@queue_bp.route('/queue/join', methods=['POST'])
def queue_join():
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    competency_ids = request.form.getlist('competency_ids')
    if competency_ids:
        with db.cursor() as sql:
            # No seat yet: students sign up before they reach the lab. They enter a
            # seat once they are sitting down (queue_seat), and that is what makes
            # them visible to staff.
            #
            # If they are already seated, carry that seat onto the new requests so
            # they do not have to say where they are twice.
            row = sql.execute(
                """select seat from requests
                    where student_number = ? and seat is not null and seat != ''
                      and status in ('waiting', 'claimed')
                    limit 1""",
                (user,)
            ).fetchone()
            seat = row[0] if row else None
            # Enforce the daily cap: only insert up to the student's remaining
            # allowance, dropping any extras they selected past the limit.
            remaining = db.daily_cap() - db.requests_used_today(sql, user)
            to_add = competency_ids[:remaining] if remaining > 0 else []
            for cid in to_add:
                sql.execute(
                    """insert into requests (student_number, competency_id, seat, requested_at, status)
                       values (?, ?, ?, CURRENT_TIMESTAMP, 'waiting')""",
                    (user, cid, seat)
                )
        skipped = len(competency_ids) - len(to_add)
        if skipped > 0:
            session['queue_notice'] = (
                'Daily limit is ' + str(db.daily_cap()) + ' competencies. '
                + str(skipped) + ' of your selections were not added.'
            )
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/seat', methods=['POST'])
def queue_seat():
    # The student arrived and sat down, moved machines, or left. An empty seat means
    # gone: they drop out of the staff queue without losing what they signed up for.
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    seat = request.form.get('seat', '').strip()
    with db.cursor() as sql:
        db.set_seat(sql, user, seat or None)
    if seat:
        session['queue_notice'] = 'Seat ' + seat + ' saved. A TA will come to you.'
    else:
        session['queue_notice'] = ('Marked as away. You are still signed up, but '
                                   'staff will not see you until you enter a seat.')
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/cancel/<int:request_id>', methods=['POST'])
def queue_cancel(request_id):
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        # Only a request nobody has taken yet. Once a TA has claimed it they are on
        # their way over, and cancelling would pull the student out from under them.
        sql.execute(
            "delete from requests where id = ? and student_number = ? and status = 'waiting'",
            (request_id, user)
        )
    return redirect(url_for('queue.queue'))


# A queue request can be marked with the same two recorded outcomes as the mark
# page: 'achieved', or 'cooling_off' (shown as "Not passed").
QUEUE_MARK_STATES = {'achieved', 'cooling_off'}


def mark_return_url(student_number, competency_id):
    # The same request can be marked from the per-student screen or from a
    # by-competency cohort. ?back=competency says which one we came from, so the
    # TA lands back where they were working instead of being bounced to the other.
    if request.args.get('back') == 'competency':
        return url_for('queue.queue_cohort', competency_id=competency_id)
    return url_for('queue.queue_evaluate', student_number=student_number)


@queue_bp.route('/queue/student/<student_number>')
def queue_evaluate(student_number):
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    return queue_evaluate_view(student_number, user)


@queue_bp.route('/queue/claim/<student_number>', methods=['POST'])
def queue_claim(student_number):
    # Taking a student out of every other TA's queue and opening their evaluation
    # screen is one action, so two TAs can never both be walking to the same seat.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        won = db.claim_student(sql, student_number, user)
    if not won:
        # Another TA claimed this student between our page rendering and our tap.
        # Nothing was changed; send us back to a queue that no longer lists them.
        session['queue_notice'] = 'Another TA just claimed that student.'
        return redirect(url_for('queue.queue'))
    return redirect(url_for('queue.queue_evaluate', student_number=student_number))


@queue_bp.route('/queue/release/<student_number>', methods=['POST'])
def queue_release(student_number):
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        db.release_student(sql, student_number, user)
    session['queue_notice'] = 'Student released back to the queue.'
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/decline/<int:request_id>', methods=['POST'])
def queue_decline(request_id):
    # "I can't evaluate this one." Hands a single competency back to the queue for
    # another TA or the instructor, without failing the student and without
    # disturbing the rest of what this TA claimed for them.
    #
    # A declined request is indistinguishable from one that was never claimed: it
    # goes back to plain 'waiting'. That deliberately means it can find its way to
    # this same TA again. Tracking who declined would need a column, a filter on
    # the queue query, and an answer for "what if everyone declines it" that ends
    # with the request invisible to the instructor who is meant to catch it.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        # Look up before releasing: afterwards the claim is gone and we could no
        # longer prove this request was ours to decline.
        req = sql.execute(
            """select r.student_number, r.competency_id, c.name from requests r
                 join competencies c on r.competency_id = c.id
                where r.id = ? and r.status = 'claimed' and r.claimed_by = ?""",
            (request_id, user)
        ).fetchone()
        if req is None:
            # Not ours (stale claim, someone else took the student, already marked).
            return redirect(url_for('queue.queue'))
        student_number, competency_id, comp_name = req
        db.release_request(sql, request_id, user)
    session['queue_notice'] = (
        comp_name + ' went back to the queue for another evaluator.'
    )
    return redirect(mark_return_url(student_number, competency_id))


@queue_bp.route('/queue/competency/<int:competency_id>')
def queue_cohort(competency_id):
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    return queue_cohort_view(competency_id, user)


@queue_bp.route('/queue/claim-group/<int:competency_id>', methods=['POST'])
def queue_claim_group(competency_id):
    # Take everyone waiting on one competency, so they can be evaluated as a batch.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        won, lost = db.claim_competency_group(sql, competency_id, user)
    if won == 0:
        session['queue_notice'] = 'Another TA just claimed those students.'
        return redirect(url_for('queue.queue', group='competency'))
    if lost > 0:
        # A partial win. Say so rather than quietly showing a short cohort, or the
        # TA thinks students went missing.
        session['queue_notice'] = (
            str(lost) + ' of those students had just been claimed by another TA.'
        )
    return redirect(url_for('queue.queue_cohort', competency_id=competency_id))


@queue_bp.route('/queue/release-group/<int:competency_id>', methods=['POST'])
def queue_release_group(competency_id):
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        db.release_students_for_competency(sql, competency_id, user)
    session['queue_notice'] = 'Students released back to the queue.'
    return redirect(url_for('queue.queue', group='competency'))


@queue_bp.route('/queue/mark/<int:request_id>/<state>', methods=['POST'])
def queue_mark(request_id, state):
    # Record the result on the student's achievements AND clear the request, in one
    # action. Scoped to requests this evaluator has claimed, so a TA cannot mark a
    # student who is being evaluated by someone else.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    if state not in QUEUE_MARK_STATES:
        return redirect(url_for('queue.queue'))
    with db.cursor() as sql:
        req = sql.execute(
            """select student_number, competency_id from requests
                where id = ? and status = 'claimed' and claimed_by = ?""",
            (request_id, user)
        ).fetchone()
        if req is None:
            return redirect(url_for('queue.queue'))
        student_number, competency_id = req
        sql.execute(
            "insert or replace into achievements (student_number, competency_id, status, date_recorded) values (?, ?, ?, CURRENT_TIMESTAMP)",
            (student_number, competency_id, state)
        )
        sql.execute(
            "update requests set status = 'done' where id = ?",
            (request_id,)
        )
        # Remember this mark so the evaluation screen can offer a one-shot Undo.
        session['queue_undo'] = {'rid': request_id, 'state': state}
    return redirect(mark_return_url(student_number, competency_id))


@queue_bp.route('/queue/undo/<int:request_id>', methods=['POST'])
def queue_undo(request_id):
    # Reverse the most recent mark: drop the recorded result and put the request
    # back to 'claimed' by this evaluator, NOT to 'waiting'. A mis-tap should hand
    # the competency back to the TA standing at the desk, not throw the student
    # back into the global queue for someone else to pick up.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        req = sql.execute(
            "select student_number, competency_id from requests where id = ?",
            (request_id,)
        ).fetchone()
        if req is None:
            return redirect(url_for('queue.queue'))
        student_number, competency_id = req
        sql.execute(
            "delete from achievements where student_number = ? and competency_id = ?",
            (student_number, competency_id)
        )
        sql.execute(
            """update requests
                  set status = 'claimed', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP
                where id = ?""",
            (user, request_id)
        )
    return redirect(mark_return_url(student_number, competency_id))
