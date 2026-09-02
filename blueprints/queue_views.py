"""Page-building for the evaluation queue: the student view, the staff
who's-next view, the cohort view, and the per-student evaluation screen.
These build HTML from data; the routes that call them live in queue.py.
"""
from flask import url_for, session
from myhtml import *
import db
import logic
from common import current_user, page_header, lab_check


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
    studios = logic.upcoming_studios(db.studio_lookahead())
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
        # Their cap can be higher than the base if they missed sessions last week (#70).
        cap = logic.session_cap_for(db.daily_cap(), db.attended_days(sql, student_number))
        remaining = {
            day: cap - db.requests_used_for_studio(sql, student_number, day)
            for day in studios
        }
        present_today = db.is_present(sql, student_number, today)
    # Seat and "a TA is coming" describe the session happening right now, so they
    # only ever read from today's requests. A booking for next Tuesday must not
    # make the student look seated and waiting today.
    seat = next((row[3] for row in pending if row[3] and row[5] == today), None)
    being_evaluated = any(row[4] == 'claimed' and row[5] == today for row in pending)
    has_today = any(row[5] == today for row in pending)
    # Seat entry: the one "I am here" action, and the only thing in this app gated to
    # being physically in the studio (#46). It was two actions before, a seat and a
    # separate "I'm here today" button, both writing attendance; Dave's call was that
    # the seat already says it, so the button is gone.
    #
    # Shown on any studio day, not only when something is booked for today, because
    # entering a seat is also how a student who came to work rather than be evaluated
    # gets counted present, and how a bumped competency (#19/#24) is carried forward.
    if logic.is_studio_day(today):
        in_lab, address, hostname = lab_check()
        if not in_lab:
            # Say what was actually resolved (#100). The pattern this is tested against
            # came from CS systems' naming convention and has never been checked on a
            # real studio machine. If it is wrong, every student in the room is refused,
            # and a message that only says "use a lab machine" tells nobody why.
            #
            # So the first blocked student's screen carries the answer: whoever is
            # standing next to them can read the real name off it and put it in the
            # lab_host_pattern setting, which is a row update and takes effect at once.
            notice = div('Seat numbers can only be entered from a lab machine in the '
                         'studio.').classes('queue-notice')
            if hostname:
                notice += span('This machine says it is ' + hostname + '.'
                               ).classes('queue-card-seat')
            elif address:
                notice += span('This machine has no name we could look up.'
                               ).classes('queue-card-seat')
            notice += span('If you are in the studio, show this to a TA.'
                           ).classes('queue-card-seat')
            p += notice
        else:
            # Students sign up before they get to the lab, so a request starts with no
            # seat. Until they enter one, staff cannot see them: there is nowhere to
            # walk to. Entering a seat is what puts them in front of a TA.
            if being_evaluated:
                p += div('A TA is on their way to you.').classes('queue-seat-set')
            elif seat:
                p += div(
                    span('You are at seat ' + seat + '. A TA will come to you.'),
                ).classes('queue-seat-set')
            elif has_today:
                p += div('Enter your seat number so a TA can find you. Staff cannot '
                         'see you until you do.').classes('queue-notice')
            elif present_today:
                p += div('You are marked present for today. See you next session.'
                         ).classes('queue-seat-set')
            f = form(method='post', action=url_for('queue.queue_seat'))
            f += span('Where are you sitting?' if not seat else 'Moved spots?')
            # Free text, not just a machine number: students may bring their own
            # laptop and sit anywhere, so a location like "back-left table" is fine.
            f += input(type='text', name='seat', value=seat or '',
                       placeholder='e.g. 12 or "back-left table"')
            f += button('I am here' if not seat else 'Update seat',
                        type='submit').classes('roster-link')
            # Stack top-to-bottom so the order reads clearly: prompt, then the box to
            # type the seat, then the button last.
            p += div(f).classes('queue-seat-entry')
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
        hint = 'Up to ' + str(cap) + ' competencies per studio session'
        if len({course for (_cid, _name, course) in all_competencies}) > 1:
            hint += (', and keep your two courses within 1 of each other '
                     '(for example 2 of one and 1 of the other)')
        hint += ('. Pick the session you want to be evaluated in: you can book '
                 'ahead, not just for today.')
        p += div(hint).classes('queue-allowance')
        # Say why the number is higher than usual, or a student who missed a week
        # sees an unexplained 12 and assumes it is a bug (#70).
        if cap > db.daily_cap():
            p += div('Higher than usual: you missed sessions last week, and these '
                     'extra slots only last this week.').classes('queue-allowance')
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
            # Against THIS student's cap, not the base one (#106). A student who
            # missed sessions last week gets extra slots, and remaining[] already
            # counts against the raised number, so pairing it with the base cap
            # read "12 of 3 left" on the one screen where the extra slots are the
            # whole point.
            text += ' - ' + str(remaining[day]) + ' of ' + str(cap) + ' left'
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
        # The available list can be long (up to 80 competencies), so keep the submit
        # button pinned to the bottom of the screen instead of at the very end (#UX).
        f += div(button('Sign up', type='submit').classes('roster-link')).classes('queue-signup-bar')
        p += f
    elif available and not bookable:
        # Their cap, not the base one, for the same reason as the picker above (#106).
        p += div('Every upcoming studio session is full for you (' + str(cap)
                 + ' competencies each). Come back after your next session.'
                 ).classes('queue-empty')
    elif not pending:
        p += div('Nothing to sign up for right now.').classes('queue-empty')
    return str(p)


def queue_staff_view(group_by='student', day=None):
    evaluator = current_user()[0]   # the TA viewing, so we can flag their bumps (#24)
    today = logic.today_toronto().isoformat()
    studios = logic.upcoming_studios(db.studio_lookahead())
    # The session being worked. Defaults to the soonest (today when it runs); a
    # TA can switch to a future one to plan, but only real studio days are valid.
    if day not in studios:
        day = studios[0]
    p = page()
    p += page_header()
    p += h1('Evaluation queue')
    nav = div().classes('subnav')
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
        # Furthest behind first (#69). The queue used to be first-come-first-served,
        # which is a fairness rule of its own; Dave's is a different one: when a session
        # runs out of time, the people who miss out should be the ones who can most
        # afford to. Python's sort is stable, so students on the same completion keep
        # the requested_at order the query already gave us, and first-come-first-served
        # still decides between equals.
        if not planning:
            behind = db.completion_by_student(sql)
            rows.sort(key=lambda row: behind.get(row[0], 0))
        # Students booked today with no seat yet. Invisible on the queue above by
        # design (a claim means walking over to someone, and there is nowhere to walk
        # to), but staff still need to see who has not turned up, and to set a seat on
        # a student's behalf when the student cannot: a DNS blip, a machine with no
        # reverse entry, their own laptop (#46). Only for the live session; on a future
        # one nobody has a seat yet and the list would be everybody.
        awaiting = [] if planning else db.students_awaiting_seat(sql, day)
    if not rows and not awaiting:
        empty = 'Queue is empty.' if not planning else 'Nobody has booked this session yet.'
        p += div(empty).classes('queue-empty')
        return str(p)
    if rows and group_by == 'competency':
        p += queue_by_competency(rows, day, claimable=not planning, evaluator=evaluator)
    elif rows:
        p += queue_by_student(rows, day, claimable=not planning, evaluator=evaluator)
    if awaiting:
        p += h2('Signed up, no seat yet')
        p += div('Nobody can claim them until they have a seat.').classes('subnav')
        for (number, first, last, how_many) in awaiting:
            f = form(method='post',
                     action=url_for('queue.queue_seat_for', student_number=number))
            f += span(last + ', ' + first).classes('progress-name')
            f += span(str(how_many)
                      + (' competency' if how_many == 1 else ' competencies')
                      ).classes('progress-badge')
            f += input(type='text', name='seat', placeholder='Seat')
            f += button('Set seat', type='submit').classes('roster-link')
            p += div(f).classes('awaiting-row')
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
        # The same third option as the per-student screen (#102). Every row here is one
        # student's request for this one competency, so handing it back means exactly
        # what it means there.
        #
        # It was missing, and the only way out was releasing the whole cohort. A TA who
        # has done five of six and hits one they cannot assess had to give back the
        # five they were about to do as well, which is a bad trade for a common case.
        actions += form(
            button("Can't evaluate", type='submit').classes('roster-link', 'queue-defer'),
            method='post',
            action=url_for('queue.queue_decline', request_id=rid, back='competency')
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
