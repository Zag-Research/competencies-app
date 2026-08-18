"""Queue behaviour: the seat gate, claiming, releasing, and declining.

These run against a throwaway SQLite file built from schema.sql, so nothing here
can touch the real course-data.db. db.DB_PATH is monkeypatched per test, and
every helper goes through db.cursor() exactly like the app does.
"""
import sqlite3

import pytest

import db as db_module
import logic


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh database with two students and two competencies."""
    path = tmp_path / 'test.db'
    with open('schema.sql') as f:
        schema = f.read()
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    with db_module.cursor() as sql:
        sql.execute("insert into students values ('Alice', 'Chen', '500111111')")
        sql.execute("insert into students values ('Ben', 'Okafor', '500222222')")
        sql.execute("insert into competencies (id, name) values (1, 'Nested loops')")
        sql.execute("insert into competencies (id, name) values (2, 'Recursion')")
    return db_module


# A fixed studio day for the db-level tests (a real Tuesday session).
STUDIO = '2026-07-28'


def add_request(student_number, competency_id, seat='12', studio_date=STUDIO):
    """Put a student in the queue, the way queue_join does."""
    with db_module.cursor() as sql:
        sql.execute(
            """insert into requests
                   (student_number, competency_id, seat, requested_at, status, studio_date)
               values (?, ?, ?, CURRENT_TIMESTAMP, 'waiting', ?)""",
            (student_number, competency_id, seat, studio_date)
        )
        return sql.lastrowid


def request_row(request_id):
    with db_module.cursor() as sql:
        return sql.execute(
            'select status, claimed_by from requests where id = ?', (request_id,)
        ).fetchone()


# --- the seat gate -------------------------------------------------------

def test_request_without_a_seat_cannot_be_claimed(db):
    """Signing up from home is a plan, not a person a TA can walk over to."""
    add_request('500111111', 1, seat=None)
    with db.cursor() as sql:
        assert db.claim_student(sql, '500111111', 'dmason', STUDIO) is False


def test_request_with_a_seat_can_be_claimed(db):
    add_request('500111111', 1, seat='12')
    with db.cursor() as sql:
        assert db.claim_student(sql, '500111111', 'dmason', STUDIO) is True


# --- claiming (#14) ------------------------------------------------------

def test_second_ta_loses_the_race(db):
    """The conditional UPDATE is what stops two TAs walking to the same seat."""
    add_request('500111111', 1)
    with db.cursor() as sql:
        assert db.claim_student(sql, '500111111', 'dmason', STUDIO) is True
        assert db.claim_student(sql, '500111111', 'lfortune', STUDIO) is False
    assert request_row(1) == ('claimed', 'dmason')


def test_claiming_takes_the_whole_student(db):
    """A student talks to one TA, so claiming takes everything they asked for."""
    first = add_request('500111111', 1)
    second = add_request('500111111', 2)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
    assert request_row(first) == ('claimed', 'dmason')
    assert request_row(second) == ('claimed', 'dmason')


def test_release_student_returns_everything(db):
    first = add_request('500111111', 1)
    second = add_request('500111111', 2)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_student(sql, '500111111', 'dmason')
    assert request_row(first) == ('waiting', None)
    assert request_row(second) == ('waiting', None)


def test_claim_group_takes_everyone_waiting_on_a_competency(db):
    add_request('500111111', 1)
    add_request('500222222', 1)
    with db.cursor() as sql:
        won, lost = db.claim_competency_group(sql, 1, 'dmason', STUDIO)
    assert (won, lost) == (2, 0)


def test_cohort_view_survives_a_cleared_seat(db, staff):
    """A claimed student who clears their seat must not crash the cohort page.

    'I have left the lab' sets the seat to None on an already-claimed request. The
    cohort view used to render 'seat ' + None and 500; now it shows 'booked'.
    """
    add_request('500111111', 1)                            # seat defaults to '12'
    with db.cursor() as sql:
        db.claim_competency_group(sql, 1, 'dmason', STUDIO)   # TA takes the cohort
        db.set_seat(sql, '500111111', None, STUDIO)           # student leaves -> seat cleared
    resp = staff.get('/queue/competency/1')
    assert resp.status_code == 200                         # no 500
    assert 'booked' in resp.get_data(as_text=True)         # shows "booked", not a crash


# --- declining a single competency (#19) ---------------------------------

def test_decline_releases_only_that_competency(db):
    """The point of the feature: hand back one, keep the rest of the sitting."""
    declined = add_request('500111111', 1)
    kept = add_request('500111111', 2)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        assert db.release_request(sql, declined, 'dmason') is True
    assert request_row(declined) == ('waiting', None)
    assert request_row(kept) == ('claimed', 'dmason')


def test_decline_records_who_bumped_it(db):
    """Declining stamps bumped_by with the TA, so the queue can flag it later."""
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, declined, 'dmason')
        bumped_by = sql.execute(
            'select bumped_by from requests where id = ?', (declined,)
        ).fetchone()[0]
    assert bumped_by == 'dmason'


def test_queue_flags_students_you_bumped(db, monkeypatch):
    """The by-student queue flags a student whose competency the viewing TA bumped,
    and only for that TA (#24)."""
    from datetime import date
    import app as app_module
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))  # STUDIO
    monkeypatch.setattr(logic, 'upcoming_studios', lambda *a, **k: [STUDIO])
    rid = add_request('500111111', 1)                 # seat '12', dated STUDIO
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')        # dmason bumps it

    def queue_as(username):
        c = app_module.app.test_client()
        with c.session_transaction() as s:
            s['user'] = username
            s['role'] = 'staff'
        return c.get('/queue').get_data(as_text=True)

    assert 'you bumped this student before' in queue_as('dmason')
    assert 'you bumped this student before' not in queue_as('lfortune')


def test_bumped_competency_follows_the_student(db, monkeypatch):
    """A bumped competency moves to whatever session the student next shows up for."""
    from datetime import date
    import app as app_module
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 29))  # a Wednesday
    rid = add_request('500111111', 1)                # dated STUDIO (Tue 2026-07-28)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')       # bumped on Tuesday
    # The student shows up Wednesday and takes a seat.
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    c.post('/queue/seat', data={'seat': '5'})
    with db.cursor() as sql:
        moved = sql.execute(
            'select studio_date from requests where id = ?', (rid,)
        ).fetchone()[0]
    assert moved == '2026-07-29'   # carried to Wednesday, the session they attended


def test_student_sees_carried_over_for_a_bumped_competency(db, monkeypatch):
    """The student's queue shows a bumped competency as carried over, not cancellable."""
    from datetime import date
    import app as app_module
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))  # STUDIO
    rid = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')   # bumped
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    body = c.get('/queue').get_data(as_text=True)
    assert 'carried over' in body


def test_cannot_cancel_a_bumped_competency(db):
    """A carried-over competency must survive a Cancel POST (e.g. from a stale tab
    that still shows the button), or the #24 carry-over would be lost."""
    import app as app_module
    rid = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')   # bumped
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    c.post('/queue/cancel/' + str(rid))
    with db.cursor() as sql:
        still_there = sql.execute(
            'select count(*) from requests where id = ?', (rid,)
        ).fetchone()[0]
    assert still_there == 1   # the delete skipped it; the bump survived


def test_a_plain_request_can_still_be_cancelled(db):
    """The bumped guard must not break normal cancelling of an un-bumped request."""
    import app as app_module
    rid = add_request('500111111', 1)
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    c.post('/queue/cancel/' + str(rid))
    with db.cursor() as sql:
        gone = sql.execute(
            'select count(*) from requests where id = ?', (rid,)
        ).fetchone()[0]
    assert gone == 0


def test_taking_a_seat_carries_a_bumped_competency_forward(db, monkeypatch):
    """Showing up resurfaces a bumped competency, so a student whose only pending item
    is the bumped one is not stranded (#19/#24).

    This used to run through the "I'm here today" button. That button is gone (#46), so
    the seat form is now shown on any studio day rather than only when something is
    booked for today, which is what keeps this reachable.
    """
    from datetime import date
    import app as app_module
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 29))  # a Wednesday
    rid = add_request('500111111', 1)                # dated STUDIO (Tue 2026-07-28)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')       # bumped Tuesday
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    c.post('/queue/seat', data={'seat': '12'})
    with db.cursor() as sql:
        moved = sql.execute(
            'select studio_date from requests where id = ?', (rid,)
        ).fetchone()[0]
    assert moved == '2026-07-29'   # carried to Wednesday just by showing up


def test_seat_on_a_non_studio_day_leaves_bumped_where_it_is(db, monkeypatch):
    """A seat POST on a non-class day must not shove a bumped competency onto a date
    no staff queue shows; carry-forward is guarded to studio days."""
    from datetime import date
    import app as app_module
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 8, 1))  # a Saturday
    rid = add_request('500111111', 1)                # dated STUDIO (Tue 2026-07-28)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    c.post('/queue/seat', data={'seat': '5'})
    with db.cursor() as sql:
        where = sql.execute(
            'select studio_date from requests where id = ?', (rid,)
        ).fetchone()[0]
    assert where == STUDIO   # unchanged; not dragged onto Saturday


def test_progress_page_shows_in_the_queue_for_a_pending_competency(db):
    """A signed-up competency reads as 'In the queue' on the progress page, not a bare
    'Not assessed'."""
    import app as app_module
    add_request('500111111', 1)                      # normal pending sign-up
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    body = c.get('/view/500111111').get_data(as_text=True)
    assert 'In the queue' in body


def test_progress_page_shows_carried_over_for_a_bumped_competency(db):
    """A bumped competency reads as 'Carried over' on the progress page."""
    import app as app_module
    rid = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, rid, 'dmason')       # bumped
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    body = c.get('/view/500111111').get_data(as_text=True)
    assert 'Carried over' in body


def test_declined_competency_is_claimable_by_another_ta(db):
    """Back to plain 'waiting' means someone else can genuinely pick it up."""
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, declined, 'dmason')
        assert db.claim_student(sql, '500111111', 'lfortune', STUDIO) is True
    assert request_row(declined) == ('claimed', 'lfortune')


def test_decline_records_no_result(db):
    """Declining is not a fail: nothing lands in achievements, so no cooling-off."""
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        db.release_request(sql, declined, 'dmason')
        rows = sql.execute('select count(*) from achievements').fetchone()
    assert rows[0] == 0


def test_decline_frees_the_slot_it_used(db):
    """A bumped competency stops counting against the cap, so the student is not
    left down a slot for one a TA could not evaluate (Dave's no-penalty rule)."""
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        before = db.requests_used_for_studio(sql, '500111111', STUDIO)
        db.release_request(sql, declined, 'dmason')
        after = db.requests_used_for_studio(sql, '500111111', STUDIO)
    assert before == 1
    assert after == 0   # bumped -> no longer counts, the slot comes back


def test_cannot_decline_another_tas_claim(db):
    """A TA must not be able to bounce a request out from under someone else."""
    held = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        assert db.release_request(sql, held, 'lfortune') is False
    assert request_row(held) == ('claimed', 'dmason')


def test_cannot_decline_an_unclaimed_request(db):
    """Nothing to hand back if nobody is holding it."""
    waiting = add_request('500111111', 1)
    with db.cursor() as sql:
        assert db.release_request(sql, waiting, 'dmason') is False
    assert request_row(waiting) == ('waiting', None)


# --- the evaluation screen, end to end -----------------------------------

@pytest.fixture
def staff(db):
    """A test client already signed in as a TA."""
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = 'dmason'
        s['role'] = 'staff'
    return client


def test_evaluation_screen_offers_all_three_actions(db, staff):
    add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
    body = staff.get('/queue/student/500111111').get_data(as_text=True)
    assert 'Achieved' in body
    assert 'Not passed' in body
    # The apostrophe is escaped in the rendered label, so match on the action
    # instead: that is what the button actually does.
    assert '/queue/decline/' in body


def test_decline_endpoint_puts_it_back_and_returns_to_the_student(db, staff):
    declined = add_request('500111111', 1)
    kept = add_request('500111111', 2)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
    response = staff.post('/queue/decline/' + str(declined))
    assert response.status_code == 302
    # Straight back to the student, so the TA carries on with what is left.
    assert response.headers['Location'].endswith('/queue/student/500111111')
    assert request_row(declined) == ('waiting', None)
    assert request_row(kept) == ('claimed', 'dmason')


def test_decline_endpoint_rejects_a_student(db):
    """Students must not be able to bounce their own request off a TA."""
    import app as app_module
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    client.post('/queue/decline/' + str(declined))
    assert request_row(declined) == ('claimed', 'dmason')


def test_undo_only_works_on_your_own_mark(db, staff):
    """A TA cannot undo (and delete) another TA's recorded mark."""
    import app as app_module
    rid = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
    staff.post('/queue/mark/' + str(rid) + '/achieved')   # dmason marks it achieved
    # A different TA tries to undo dmason's mark.
    other = app_module.app.test_client()
    with other.session_transaction() as s:
        s['user'] = 'lfortune'
        s['role'] = 'staff'
    other.post('/queue/undo/' + str(rid))
    with db.cursor() as sql:
        still_there = sql.execute(
            "select count(*) from achievements"
            " where student_number = '500111111' and competency_id = 1"
        ).fetchone()[0]
    assert still_there == 1   # dmason's mark survived; lfortune could not touch it
