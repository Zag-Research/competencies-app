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
        pending = sql.execute(
            """select r.id, r.competency_id, c.name from requests r
               join competencies c on r.competency_id = c.id
               where r.student_number = ? and r.status = 'waiting'
               order by r.requested_at""",
            (student_number,)
        ).fetchall()
        pending_ids = {row[1] for row in pending}
        all_competencies = sql.execute(
            "select id, name from competencies order by id"
        ).fetchall()
        remaining_today = db.daily_cap() - db.requests_used_today(sql, student_number)
    available = []
    for (cid, name) in all_competencies:
        if cid in pending_ids:
            continue
        state = states.get(cid, 'unassessed')
        if state == 'unassessed':
            available.append((cid, name))
        elif state == 'cooling_off':
            # A cooling-off competency reappears in the sign-up list only once its
            # two-day retry window has passed.
            if logic.retry_available(recorded_at.get(cid)):
                available.append((cid, name))
    if pending:
        p += h2('In the queue')
        for (rid, _cid, name) in pending:
            p += div(
                span(name).classes('progress-name'),
                form(
                    button('Cancel', type='submit').classes('roster-link'),
                    method='post',
                    action=url_for('queue.queue_cancel', request_id=rid)
                )
            ).classes('queue-row')
    if available and remaining_today > 0:
        p += h2('Sign up')
        p += div(str(remaining_today) + ' of ' + str(db.daily_cap())
                 + ' requests left today.').classes('queue-allowance')
        f = form(method='post', action=url_for('queue.queue_join'))
        for (cid, name) in available:
            lbl = label().classes('queue-check')
            lbl += input(type='checkbox', name='competency_ids', value=str(cid))
            lbl += span(name)
            f += lbl
        f += div(
            span('Seat number'),
            input(type='text', name='seat', placeholder='e.g. 12')
        ).classes('queue-seat')
        f += button('Join queue', type='submit').classes('roster-link')
        p += f
    elif available and remaining_today <= 0:
        p += div('You have used all ' + str(db.daily_cap())
                 + ' of today\'s requests.').classes('queue-empty')
    elif not pending:
        p += div('Nothing to sign up for right now.').classes('queue-empty')
    return str(p)


def queue_staff_view():
    p = page()
    p += page_header()
    p += h1('Evaluation queue')
    p += div(a('← Back to students', href=url_for('main.index'))).classes('subnav')
    with db.cursor() as sql:
        rows = sql.execute(
            """select r.id, r.student_number, s.first_name, s.last_name,
                      c.name, r.seat
               from requests r
               join students s on r.student_number = s.student_number
               join competencies c on r.competency_id = c.id
               where r.status = 'waiting'
               order by r.requested_at"""
        ).fetchall()
    if not rows:
        p += div('Queue is empty.').classes('queue-empty')
        return str(p)
    # Group the flat rows by student so each student shows once, with all their
    # requested competencies listed under them. Insertion order (Python dict)
    # preserves the requested_at ordering from the query, so the student who has
    # waited longest stays at the top.
    students = {}
    for (rid, number, first, last, comp_name, seat) in rows:
        if number not in students:
            students[number] = {'name': last + ', ' + first, 'seat': seat, 'items': []}
        students[number]['items'].append((rid, comp_name))
    for group in students.values():
        card = div().classes('queue-card')
        card += div(
            span(group['name']).classes('queue-card-name'),
            span('seat ' + group['seat']).classes('queue-card-seat'),
        ).classes('queue-card-head')
        for (rid, comp_name) in group['items']:
            # Two one-tap outcomes per competency; each records and clears at once.
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
            card += div(
                span(comp_name).classes('progress-name'),
                actions,
            ).classes('queue-row')
        p += card
    return str(p)


@queue_bp.route('/queue')
def queue():
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if role == 'student':
        return queue_student_view(user)
    if role == 'staff':
        return queue_staff_view()
    return redirect(url_for('auth.login'))


@queue_bp.route('/queue/join', methods=['POST'])
def queue_join():
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    competency_ids = request.form.getlist('competency_ids')
    seat = request.form.get('seat', '').strip()
    if competency_ids and seat:
        with db.cursor() as sql:
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


@queue_bp.route('/queue/cancel/<int:request_id>', methods=['POST'])
def queue_cancel(request_id):
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        sql.execute(
            "delete from requests where id = ? and student_number = ?",
            (request_id, user)
        )
    return redirect(url_for('queue.queue'))


# A queue request can be marked with the same two recorded outcomes as the mark
# page: 'achieved', or 'cooling_off' (shown as "Not passed").
QUEUE_MARK_STATES = {'achieved', 'cooling_off'}


@queue_bp.route('/queue/mark/<int:request_id>/<state>', methods=['POST'])
def queue_mark(request_id, state):
    # Staff evaluates straight from the queue: record the result on the student's
    # achievements AND clear the request, in one action. Looking the student and
    # competency up from the request means the URL only needs the request id.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    if state not in QUEUE_MARK_STATES:
        return redirect(url_for('queue.queue'))
    with db.cursor() as sql:
        req = sql.execute(
            "select student_number, competency_id from requests where id = ? and status = 'waiting'",
            (request_id,)
        ).fetchone()
        if req is not None:
            student_number, competency_id = req
            sql.execute(
                "insert or replace into achievements (student_number, competency_id, status, date_recorded) values (?, ?, ?, CURRENT_TIMESTAMP)",
                (student_number, competency_id, state)
            )
            sql.execute(
                "update requests set status = 'done' where id = ?",
                (request_id,)
            )
    return redirect(url_for('queue.queue'))
