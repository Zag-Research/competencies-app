"""Queue behaviour: the seat gate, claiming, releasing, and declining.

These run against a throwaway SQLite file built from schema.sql, so nothing here
can touch the real course-data.db. db.DB_PATH is monkeypatched per test, and
every helper goes through db.cursor() exactly like the app does.
"""
import sqlite3

import pytest

import db as db_module


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


def test_decline_does_not_spend_a_daily_request(db):
    """The row already existed, so going back on the list costs the student nothing."""
    declined = add_request('500111111', 1)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', STUDIO)
        before = db.requests_used_for_studio(sql, '500111111', STUDIO)
        db.release_request(sql, declined, 'dmason')
        after = db.requests_used_for_studio(sql, '500111111', STUDIO)
    assert before == after == 1


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
