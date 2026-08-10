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
    today = logic.today_toronto().isoformat()
    studios = logic.upcoming_studios()
    with db.cursor() as sql:
        states, recorded_at = db.achievement_states(sql, student_number)
        # 'claimed' as well as 'waiting': a TA taking the student must not make their
        # own queue page go blank. They still have those requests open, and someone
        # is on the way.
        pending = sql.execute(
            """select r.id, r.competency_id, c.name, r.seat, r.status, r.studio_date,
                      r.bumped_by
               from requests r
               join competencies c on r.competency_id = c.id
               where r.student_number = ? and r.status in ('waiting', 'claimed')
               order by r.studio_date, r.requested_at""",
            (student_number,)
        ).fetchall()
        pending_ids = {row[1] for row in pending}
        # Only the student's enrolled courses (#11): a part-time student cannot
        # sign up for the other course's competencies.
        all_competencies = db.competencies_for(sql, student_number)
        # Allowance is per studio session, so a student can plan a week ahead
        # without spending one day's worth of slots.
        remaining = {
            day: db.daily_cap() - db.requests_used_for_studio(sql, student_number, day)
            for day in studios
        }
        present_today = db.is_present(sql, student_number, today)
    # Attendance is its own thing, shown only on a day the studio actually runs.
    # It stands apart from signing up or taking a seat: a student who just comes to
    # work still checks in, so "was here" is captured for everyone, not only those
    # who demo a competency.
    if logic.is_studio_day(today):
        if present_today:
            p += div('You are checked in for today. See you next session.'
                     ).classes('queue-seat-set')
        else:
            check = form(method='post', action=url_for('queue.queue_checkin'))
            check += span('Here for today\'s session? ')
            check += button("I'm here today", type='submit').classes('roster-link')
            p += div(check).classes('queue-checkin')
    # Seat and "a TA is coming" describe the session happening right now, so they
    # only ever read from today's requests. A booking for next Tuesday must not
    # make the student look seated and waiting today.
    seat = next((row[3] for row in pending if row[3] and row[5] == today), None)
    being_evaluated = any(row[4] == 'claimed' and row[5] == today for row in pending)
    has_today = any(row[5] == today for row in pending)
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
        # The seat only means anything for the session running today, so the whole
        # seat block is skipped when everything booked is for a future session.
        if has_today:
            # Students sign up before they get to the lab, so a request starts with
            # no seat. Until they enter one, staff cannot see them: there is nowhere
            # to walk to. Entering a seat is what puts them in front of a TA.
            if being_evaluated:
                p += div('A TA is on their way to you.').classes('queue-seat-set')
            elif seat:
                p += div(
                    span('You are at seat ' + seat + '. A TA will come to you.'),
                ).classes('queue-seat-set')
            else:
                p += div('You are signed up for today. Enter your seat number when '
                         'you get to the lab, so a TA can find you. You will not '
                         'appear in the staff queue until you do.').classes('queue-notice')
            f = form(method='post', action=url_for('queue.queue_seat'))
            f += span('Where are you sitting?' if not seat else 'Moved spots?')
            # Free text, not just a machine number: students may bring their own
            # laptop and sit anywhere, so a location like "back-left table" is fine.
            f += input(type='text', name='seat', value=seat or '',
                       placeholder='e.g. 12 or "back-left table"')
            f += button('I am here' if not seat else 'Update seat',
                        type='submit').classes('roster-link')
            p += div(f).classes('queue-seat')
        current_day = None
        for (rid, _cid, name, _seat, status, studio_date, bumped_by) in pending:
            # A heading per session, so a student can see what they booked for
            # today versus what is waiting for them next Tuesday.
            if studio_date != current_day:
                current_day = studio_date
                heading = logic.studio_label(studio_date)
                if studio_date == today:
                    heading += ' (today)'
                p += div(heading).classes('queue-course')
            row = div(span(name).classes('progress-name')).classes('queue-row')
            if status == 'claimed':
                # A TA is already standing up to come over. Cancelling now would
                # pull the student out from under them.
                row += span('being evaluated').classes('queue-card-seat')
            elif bumped_by:
                # A TA could not get to it; it is carried over and waiting for the
                # student, so no action is needed and no Cancel is offered (#19).
                row += span('carried over, we will get to it next time'
                            ).classes('queue-card-seat')
            else:
                row += form(
                    button('Cancel', type='submit').classes('roster-link'),
                    method='post',
                    action=url_for('queue.queue_cancel', request_id=rid)
                )
            p += row
        if seat:
            # Leaving clears today's seat, which drops them out of the staff queue
            # without cancelling what they signed up for.
            p += form(
                button('I have left the lab', type='submit').classes('roster-link'),
                method='post',
                action=url_for('queue.queue_seat')
            ).classes('queue-release')
    bookable = [day for day in studios if remaining[day] > 0]
    if available and bookable:
        p += h2('Sign up')
        # The balance rule only applies to a student in more than one course, so the
        # "keep your two courses within 1" line is shown only to them; a single-course
        # student would otherwise read a rule about a course they are not taking (#11).
        hint = 'Up to ' + str(db.daily_cap()) + ' competencies per studio session'
        if len({course for (_cid, _name, course) in all_competencies}) > 1:
            hint += (', and keep your two courses within 1 of each other '
                     '(for example 2 of one and 1 of the other)')
        hint += ('. Pick the session you want to be evaluated in: you can book '
                 'ahead, not just for today.')
        p += div(hint).classes('queue-allowance')
        f = form(method='post', action=url_for('queue.queue_join'))
        # Which session these competencies are for. Only sessions with room left
        # are offered, so a student cannot book into a full day and be silently
        # trimmed. Defaults to the soonest session with space.
        picker = div(span('Studio session ')).classes('queue-seat')
        sel = select(name='studio_date').classes('endorse-select')
        for day in bookable:
            text = logic.studio_label(day)
            if day == today:
                text += ' (today)'
            text += ' - ' + str(remaining[day]) + ' of ' + str(db.daily_cap()) + ' left'
            o = option(text, value=day)
            if day == bookable[0]:
                o.addAttributes(selected=True)
            sel += o
        picker += sel
        f += picker
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
    elif available and not bookable:
        p += div('Every upcoming studio session is full for you (' + str(db.daily_cap())
                 + ' competencies each). Come back after your next session.'
                 ).classes('queue-empty')
    elif not pending:
        p += div('Nothing to sign up for right now.').classes('queue-empty')
    return str(p)


def queue_staff_view(group_by='student', day=None):
    evaluator = current_user()[0]   # the TA viewing, so we can flag their bumps (#24)
    today = logic.today_toronto().isoformat()
    studios = logic.upcoming_studios()
    # The session being worked. Defaults to the soonest (today when it runs); a
    # TA can switch to a future one to plan, but only real studio days are valid.
    if day not in studios:
        day = studios[0]
    p = page()
    p += page_header()
    p += h1('Evaluation queue')
    nav = div(a('← Back to students', href=url_for('main.index'))).classes('subnav')
    # Same requests, two groupings: work through one student at a time, or work
    # through everyone who wants the same competency. Links carry the session so
    # switching grouping keeps the day.
    for (key, text) in (('student', 'By student'), ('competency', 'By competency')):
        link = a(text, href=url_for('queue.queue', group=key, day=day)).classes('queue-toggle')
        if key == group_by:
            link.addClasses('is-active')
        nav += link
    p += nav
    # Which studio session's queue to show. Today by default; the other links let a
    # TA look ahead at what students have booked.
    dayrow = div(span('Session ')).classes('subnav')
    for d in studios:
        text = logic.studio_label(d) + (' (today)' if d == today else '')
        link = a(text, href=url_for('queue.queue', group=group_by, day=d)).classes('queue-toggle')
        if d == day:
            link.addClasses('is-active')
        dayrow += link
    p += dayrow
    # One-shot notice, e.g. losing a race to claim a student, or releasing one.
    notice = session.pop('queue_notice', None)
    if notice:
        p += div(notice).classes('queue-notice')
    # Today is the live, claimable queue: seat-gated, because a claim means walking
    # over to someone who is here. A future session is a read-only planning roster:
    # those students have booked but are not in the lab, so it shows everything
    # they signed up for, seat or not, and nothing is claimable yet.
    planning = day != today
    with db.cursor() as sql:
        if planning:
            p += div('Planning view: these students have booked '
                     + logic.studio_label(day) + '. You can see what is coming, '
                     'but claiming opens on the day.').classes('queue-notice')
            rows = sql.execute(
                """select r.student_number, s.first_name, s.last_name,
                          r.competency_id, c.name, r.seat, r.bumped_by
                     from requests r
                     join students s on r.student_number = s.student_number
                     join competencies c on r.competency_id = c.id
                    where r.studio_date = ? and r.status = 'waiting'
                    order by r.requested_at""",
                (day,)
            ).fetchall()
        else:
            rows = sql.execute(
                """select r.student_number, s.first_name, s.last_name,
                          r.competency_id, c.name, r.seat, r.bumped_by
                     from requests r
                     join students s on r.student_number = s.student_number
                     join competencies c on r.competency_id = c.id
                    where """ + db.AVAILABLE + """
                    order by r.requested_at""",
                (day, db.claim_cutoff())
            ).fetchall()
    if not rows:
        empty = 'Queue is empty.' if not planning else 'Nobody has booked this session yet.'
        p += div(empty).classes('queue-empty')
        return str(p)
    if group_by == 'competency':
        p += queue_by_competency(rows, day, claimable=not planning, evaluator=evaluator)
    else:
        p += queue_by_student(rows, day, claimable=not planning, evaluator=evaluator)
    return str(p)


def seat_label(seat):
    # Booked-ahead requests have no seat yet, so the planning view can be handed a
    # None. Show where to walk when we know, and "booked" when we do not.
    return 'seat ' + seat if seat else 'booked'


def queue_card(claimable, action, head, body_rows):
    # One queue card. On the live queue it is a claim button (tapping it claims the
    # whole card and opens the evaluation screen). In the planning view it is a
    # plain, non-interactive card: those students are not here to be claimed yet.
    inner = div(head, *body_rows)
    if claimable:
        b = button(type='submit').classes('queue-card', 'queue-claim')
        b += inner
        return form(b, method='post', action=action)
    return div(inner).classes('queue-card')


def queue_by_student(rows, day, claimable=True, evaluator=None):
    # Group the flat rows by student so each student shows once, with all their
    # requested competencies listed under them. Insertion order (Python dict)
    # preserves the requested_at ordering from the query, so the student who has
    # waited longest stays at the top.
    students = {}
    for (number, first, last, _cid, comp_name, seat, bumped_by) in rows:
        if number not in students:
            students[number] = {'name': last + ', ' + first, 'seat': seat,
                                 'items': [], 'bumped': False}
        students[number]['items'].append(comp_name)
        # Flag the student if THIS TA bumped one of their competencies (#24), so
        # they can pick it back up (or steer clear).
        if bumped_by and bumped_by == evaluator:
            students[number]['bumped'] = True
    out = div()
    for (number, group) in students.items():
        head = div(
            span(group['name']).classes('queue-card-name'),
            span(seat_label(group['seat'])).classes('queue-card-seat'),
        ).classes('queue-card-head')
        if group['bumped']:
            head += span('you bumped this student before').classes('queue-bumped')
        body_rows = [div(span(name).classes('progress-name')).classes('queue-row')
                     for name in group['items']]
        out += queue_card(
            claimable,
            url_for('queue.queue_claim', student_number=number, day=day),
            head, body_rows)
    return out


def queue_by_competency(rows, day, claimable=True, evaluator=None):
    # Same rows, grouped the other way: one card per competency, listing everyone
    # waiting on it, so a TA can evaluate the whole cohort in one pass instead of
    # repeating the same evaluation student by student. (evaluator is accepted for a
    # matching signature; the bumped flag is a by-student cue, not a per-competency one.)
    comps = {}
    for (_number, first, last, cid, comp_name, seat, _bumped_by) in rows:
        if cid not in comps:
            comps[cid] = {'name': comp_name, 'students': []}
        comps[cid]['students'].append((last + ', ' + first, seat))
    out = div()
    for (cid, group) in comps.items():
        count = len(group['students'])
        head = div(
            span(group['name']).classes('queue-card-name'),
            span(str(count) + (' student' if count == 1 else ' students')
                 ).classes('queue-card-seat'),
        ).classes('queue-card-head')
        body_rows = [
            div(span(name).classes('progress-name'),
                span(seat_label(seat)).classes('queue-card-seat')).classes('queue-row')
            for (name, seat) in group['students']
        ]
        out += queue_card(
            claimable,
            url_for('queue.queue_claim_group', competency_id=cid, day=day),
            head, body_rows)
    return out


def competency_scope(description):
    """The competency's sub-points, rendered so a TA can scan them.

    Descriptions are stored as the source document's sub-points joined with
    '; '. Split them back out: a seven-point competency like Flip Flops is
    unreadable as one run-on line but fine as seven bullets. A competency whose
    scope is a single phrase stays plain text rather than a one-item list.
    """
    parts = [part.strip() for part in description.split(';') if part.strip()]
    if len(parts) <= 1:
        return div(description).classes('competency-scope')
    items = ul().classes('competency-scope')
    for part in parts:
        items += li(part)
    return items


def queue_cohort_view(competency_id, evaluator):
    """The claimed cohort: everyone this TA took for one competency, marked together."""
    p = page()
    p += page_header()
    undo = session.pop('queue_undo', None)
    with db.cursor() as sql:
        comp = sql.execute(
            "select name, description from competencies where id = ?",
            (competency_id,)
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
    # Scope for the one competency this whole cohort is being evaluated on.
    if comp[1]:
        p += competency_scope(comp[1])
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
            span(seat_label(seat)).classes('queue-card-seat'),
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
            """select r.id, c.name, r.seat, c.description
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
    for (rid, comp_name, _seat, comp_desc) in rows:
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
        # The competency's sub-points, as a reminder of what this competency
        # actually covers. This is the facilitation scope: a TA who has not
        # prepared this one can see what to probe before deciding to decline it.
        who = div(span(comp_name).classes('progress-name'))
        if comp_desc:
            who += competency_scope(comp_desc)
        p += div(who, actions).classes('queue-row')
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
    if studio_date not in logic.upcoming_studios():
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

            cap = db.daily_cap()
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
        # Taking a seat is a stronger "I am here" than the check-in button, so it
        # marks attendance too. Guarded by is_studio_day like queue_checkin, so a
        # crafted POST on a non-class day can't inflate the attended count. Leaving
        # (empty seat) does not un-attend: they were still here today.
        if seat and logic.is_studio_day(today):
            db.mark_present(sql, user, today)
    if seat:
        session['queue_notice'] = 'Seat ' + seat + ' saved. A TA will come to you.'
    else:
        session['queue_notice'] = ('Marked as away. You are still signed up, but '
                                   'staff will not see you until you enter a seat.')
    return redirect(url_for('queue.queue'))


@queue_bp.route('/queue/checkin', methods=['POST'])
def queue_checkin():
    # "I'm here today." Records attendance for today's session, independent of
    # whether the student signs up for or demonstrates anything. Only counts on a
    # real studio day, so a stray tap on a weekend records nothing.
    user, role = current_user()
    if user is None or role != 'student':
        return redirect(url_for('auth.login'))
    today = logic.today_toronto().isoformat()
    if logic.is_studio_day(today):
        with db.cursor() as sql:
            db.mark_present(sql, user, today)
            # Checking in is also "I'm here", so carry any bumped competencies into
            # today too. Without this, a student whose only pending item is a bumped
            # one never sees the seat form (it needs a request dated today), so this
            # is their only way to resurface it (#19/#24).
            db.carry_bumped_forward(sql, user, today)
        session['queue_notice'] = 'Checked in for today. Thanks for coming.'
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
    if day not in logic.upcoming_studios():
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
    if day not in logic.upcoming_studios():
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
