"""The evaluation queue: student sign-up and the staff who's-next / marking view.

The page-building functions live in queue_views.py; this file holds the routes.
"""
from flask import Blueprint, request, url_for, session, redirect
from myhtml import *
import db
import logic
from common import current_user, page_header, request_is_in_lab
from blueprints.queue_views import (
    queue_student_view, queue_staff_view, queue_cohort_view, queue_evaluate_view)

queue_bp = Blueprint('queue', __name__)


@queue_bp.route('/queue')
def queue():
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if role == 'student':
        return queue_student_view(user)
    if role == 'staff':
        group = request.args.get('group')
        return queue_staff_view('competency' if group == 'competency' else 'student',
                                request.args.get('day'))
    return redirect(url_for('auth.login'))


@queue_bp.route('/queue/join', methods=['POST'])
def queue_join():
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    competency_ids = request.form.getlist('competency_ids')
    # Which session this sign-up is for. Guard it against a hand-crafted POST: only
    # a real upcoming studio day is allowed, otherwise fall back to the next one.
    studio_date = request.form.get('studio_date', '')
    if studio_date not in logic.upcoming_studios(db.studio_lookahead()):
        studio_date = logic.next_studio()
    today = logic.today_toronto().isoformat()
    if competency_ids:
        with db.cursor() as sql:
            # Only competencies in the student's enrolled courses (#11), and not ones
            # already passed; a hand-crafted POST must not book another course's
            # competency or re-request one that is already achieved.
            course_of = {str(cid): course
                         for (cid, _n, course) in db.competencies_for(sql, user)}
            achieved = db.achieved_competency_ids(sql, user)
            competency_ids = [c for c in competency_ids
                              if c in course_of and int(c) not in achieved]

            # The balance rule (#22) looks at the whole session. Start every course
            # the student can pick from at 0 (so a lopsided "2 and 0" is caught), add
            # what is already booked this session, then add the new picks. Seed from
            # course_of (the courses competencies_for returned) rather than
            # enrolled_courses: a student with no enrollment row is treated as taking
            # every course by competencies_for, and this keeps the two in agreement so
            # the rule can't be bypassed by picking all from one course.
            #
            # But drop a course the student has already finished (every competency in
            # it achieved): the balance should not throttle their remaining course to
            # 1-per-session just because a completed course sits at 0 (#26).
            comps_by_course = {}
            for (cid_str, course) in course_of.items():
                comps_by_course.setdefault(course, []).append(int(cid_str))
            counts = {course: 0 for (course, cids) in comps_by_course.items()
                      if any(cid not in achieved for cid in cids)}
            for (course, n) in db.session_course_counts(sql, user, studio_date):
                counts[course] = counts.get(course, 0) + n
            for cid in competency_ids:
                counts[course_of[cid]] = counts.get(course_of[cid], 0) + 1

            # A student who missed sessions last week gets those slots back (#70).
            # The cap spreads work across the term; someone who was ill did not choose
            # to bunch theirs, so it should not punish them for it.
            cap = logic.session_cap_for(db.daily_cap(), db.attended_days(sql, user))
            if competency_ids and not logic.session_signup_ok(counts, cap):
                # Reject the whole sign-up and say why; nothing is inserted.
                if sum(counts.values()) > cap:
                    session['queue_notice'] = (
                        'That is more than the ' + str(cap) + ' competencies you can '
                        'sign up for in one session. Pick fewer.')
                else:
                    session['queue_notice'] = (
                        'Keep your two courses within 1 of each other this session, '
                        'for example 2 of one and 1 of the other, not 3 and 0. '
                        'Adjust your picks and try again.')
                return redirect(url_for('queue.queue'))

            # Passed. A seat only means "I am here now", so only a booking for today
            # inherits today's seat; a future booking starts seatless.
            seat = None
            if studio_date == today:
                row = sql.execute(
                    """select seat from requests
                        where student_number = ? and studio_date = ?
                          and seat is not null and seat != ''
                          and status in ('waiting', 'claimed')
                        limit 1""",
                    (user, today)
                ).fetchone()
                seat = row[0] if row else None
            for cid in competency_ids:
                sql.execute(
                    """insert into requests
                           (student_number, competency_id, seat, requested_at, status, studio_date)
                       values (?, ?, ?, CURRENT_TIMESTAMP, 'waiting', ?)""",
                    (user, cid, seat, studio_date)
                )
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/seat', methods=['POST'])
def queue_seat():
    # The student arrived and sat down, moved machines, or left. An empty seat means
    # gone: they drop out of the staff queue without losing what they signed up for.
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    # The one location-gated action (#46): a seat means "I am here", so it has to come
    # from a machine that is actually here. Enforced server-side as well as hidden in
    # the view, because a hidden control is not a check.
    if not request_is_in_lab():
        session['queue_notice'] = ('Seat numbers can only be entered from a lab '
                                   'machine in the studio.')
        return redirect(url_for('queue.queue'))
    seat = request.form.get('seat', '').strip()
    # A seat is only ever about the session running today: it means "I am here, at
    # this machine, right now." Booked-ahead requests for other days are untouched.
    today = logic.today_toronto().isoformat()
    with db.cursor() as sql:
        # Showing up (taking a seat) is what a bumped competency was waiting for:
        # pull the student's bumped competencies into today's session first, so the
        # seat below lands on them too and they resurface for a TA (#19/#24). Guarded
        # by is_studio_day so a seat POST on a non-class day can't move a bumped
        # competency onto a date no staff queue ever shows.
        if seat and logic.is_studio_day(today):
            db.carry_bumped_forward(sql, user, today)
        db.set_seat(sql, user, seat or None, today)
        # Taking a seat IS "I am here", so it marks attendance. This is now the only
        # writer of attendance (#46): the separate check-in button is gone. Guarded by
        # is_studio_day so a crafted POST on a non-class day can't inflate the attended
        # count. Leaving (an empty seat) does not un-attend: they were still here.
        if seat and logic.is_studio_day(today):
            db.mark_present(sql, user, today)
    if seat:
        session['queue_notice'] = 'Seat ' + seat + ' saved. A TA will come to you.'
    else:
        session['queue_notice'] = ('Marked as away. You are still signed up, but '
                                   'staff will not see you until you enter a seat.')
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/seat-for/<student_number>', methods=['POST'])
def queue_seat_for(student_number):
    """A TA sets a student's seat on their behalf (#46).

    The student's own seat entry is gated to lab machines, which is right for a
    self-report but leaves no way out when the gate misfires: a DNS blip, a machine
    with no reverse entry, a student on their own laptop. Without this the studio
    stops, because a student with no seat is invisible to every TA.

    Deliberately NOT lab-gated itself. A TA on an iPad is on wifi, and gating the
    escape hatch on the thing that just failed would make it useless. What makes it
    trustworthy is that a TA is standing in the room asserting the student is there,
    which is a better signal than the self-report it replaces.
    """
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
    seat = request.form.get('seat', '').strip()
    today = logic.today_toronto().isoformat()
    if not seat or not logic.is_studio_day(today):
        return redirect(url_for('queue.queue'))
    with db.cursor() as sql:
        db.carry_bumped_forward(sql, student_number, today)
        db.set_seat(sql, student_number, seat, today)
        # A TA saying where a student is sitting is a stronger "they are here" than the
        # student saying it themselves, so it marks attendance the same way.
        db.mark_present(sql, student_number, today)
    session['queue_notice'] = 'Seat ' + seat + ' set for that student.'
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/cancel/<int:request_id>', methods=['POST'])
def queue_cancel(request_id):
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    with db.cursor() as sql:
        # Only a request nobody has taken yet. Once a TA has claimed it they are on
        # their way over, and cancelling would pull the student out from under them.
        # bumped_by is null keeps a carried-over competency (#24) uncancellable: the
        # student view already hides its Cancel button, but a stale tab loaded before
        # the bump would still have one, and deleting it would drop the carry-over.
        sql.execute(
            "delete from requests where id = ? and student_number = ? "
            "and status = 'waiting' and bumped_by is null",
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
    # The session whose queue this claim came from, so it only takes requests
    # booked for that day. Guarded against a bad value, defaulting to the soonest.
    day = request.args.get('day')
    if day not in logic.upcoming_studios(db.studio_lookahead()):
        day = logic.next_studio()
    with db.cursor() as sql:
        won = db.claim_student(sql, student_number, user, day)
    if not won:
        # Another TA claimed this student between our page rendering and our tap.
        # Nothing was changed; send us back to a queue that no longer lists them.
        session['queue_notice'] = 'Another TA just claimed that student.'
        return redirect(url_for('queue.queue', day=day))
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
    # Batch-claim is scoped to one session, same as the single claim above.
    day = request.args.get('day')
    if day not in logic.upcoming_studios(db.studio_lookahead()):
        day = logic.next_studio()
    with db.cursor() as sql:
        won, lost = db.claim_competency_group(sql, competency_id, user, day)
    if won == 0:
        session['queue_notice'] = 'Another TA just claimed those students.'
        return redirect(url_for('queue.queue', group='competency', day=day))
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
        db.record_achievement(sql, student_number, competency_id, state, user)
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
        # Only a request THIS evaluator just marked: status 'done' (already marked)
        # and claimed_by them. Without this, any staff user could undo another TA's
        # mark, or pull a 'waiting' request into their own claim past the AVAILABLE
        # guards. Mirrors the ownership check in queue_mark.
        req = sql.execute(
            """select student_number, competency_id from requests
                where id = ? and status = 'done' and claimed_by = ?""",
            (request_id, user)
        ).fetchone()
        if req is None:
            return redirect(url_for('queue.queue'))
        student_number, competency_id = req
        db.clear_achievement(sql, student_number, competency_id)
        sql.execute(
            """update requests
                  set status = 'claimed', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP
                where id = ?""",
            (user, request_id)
        )
    return redirect(mark_return_url(student_number, competency_id))
