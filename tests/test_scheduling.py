"""Advance scheduling (#17): studio-day rules and per-session queue scoping."""
import sqlite3
from datetime import date, timedelta

import pytest

import db as db_module
import logic


# --- pure studio-day rules (no database) ---------------------------------

def test_studio_days_are_tue_wed_thu():
    # 2026-07-27 is a Monday; walk the week.
    monday = date(2026, 7, 27)
    runs = {(monday + timedelta(days=i)).isoformat(): logic.is_studio_day(
        (monday + timedelta(days=i)).isoformat()) for i in range(7)}
    assert runs['2026-07-27'] is False  # Monday
    assert runs['2026-07-28'] is True   # Tuesday
    assert runs['2026-07-29'] is True   # Wednesday
    assert runs['2026-07-30'] is True   # Thursday
    assert runs['2026-07-31'] is False  # Friday


def test_upcoming_studios_from_a_monday_lists_the_week():
    got = logic.upcoming_studios(count=3, today=date(2026, 7, 27))
    assert got == ['2026-07-28', '2026-07-29', '2026-07-30']


def test_upcoming_includes_today_when_today_is_a_studio_day():
    got = logic.upcoming_studios(count=2, today=date(2026, 7, 29))  # a Wednesday
    assert got[0] == '2026-07-29'


def test_next_studio_skips_the_weekend():
    # Friday -> the following Tuesday.
    assert logic.next_studio(today=date(2026, 7, 31)) == '2026-08-04'


def test_studio_label_reads_naturally():
    assert logic.studio_label('2026-07-28') == 'Tuesday, July 28'


# --- per-session scoping in the queue ------------------------------------

TUE = '2026-07-28'
WED = '2026-07-29'


@pytest.fixture
def db(tmp_path, monkeypatch):
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
        sql.execute("insert into competencies (id, name) values (1, 'Nested loops')")
        sql.execute("insert into competencies (id, name) values (2, 'Recursion')")
    return db_module


def book(student_number, competency_id, studio_date, seat='12'):
    with db_module.cursor() as sql:
        sql.execute(
            """insert into requests
                   (student_number, competency_id, seat, requested_at, status, studio_date)
               values (?, ?, ?, CURRENT_TIMESTAMP, 'waiting', ?)""",
            (student_number, competency_id, seat, studio_date)
        )
        return sql.lastrowid


def status_of(request_id):
    with db_module.cursor() as sql:
        return sql.execute(
            'select status, claimed_by from requests where id = ?', (request_id,)
        ).fetchone()


def test_a_claim_only_takes_the_session_it_is_for(db):
    """A Wednesday booking must not be claimable from Tuesday's queue."""
    wed = book('500111111', 1, WED)
    with db.cursor() as sql:
        # No available request for Tuesday, so the claim finds nothing.
        assert db.claim_student(sql, '500111111', 'dmason', TUE) is False
    assert status_of(wed) == ('waiting', None)


def test_a_claim_takes_the_matching_session(db):
    wed = book('500111111', 1, WED)
    with db.cursor() as sql:
        assert db.claim_student(sql, '500111111', 'dmason', WED) is True
    assert status_of(wed) == ('claimed', 'dmason')


def test_claiming_one_session_leaves_the_other_alone(db):
    """A student booked into both days: taking Tuesday must not touch Wednesday."""
    tue = book('500111111', 1, TUE)
    wed = book('500111111', 2, WED)
    with db.cursor() as sql:
        db.claim_student(sql, '500111111', 'dmason', TUE)
    assert status_of(tue) == ('claimed', 'dmason')
    assert status_of(wed) == ('waiting', None)


def test_cap_is_counted_per_session_not_per_day(db):
    """Booking Tuesday full still leaves the whole allowance for Wednesday."""
    book('500111111', 1, TUE)
    book('500111111', 2, TUE)
    with db.cursor() as sql:
        assert db.requests_used_for_studio(sql, '500111111', TUE) == 2
        assert db.requests_used_for_studio(sql, '500111111', WED) == 0


def test_set_seat_only_touches_the_named_session(db):
    """Sitting down today must not stamp a seat on a future booking."""
    tue = book('500111111', 1, TUE, seat=None)
    wed = book('500111111', 2, WED, seat=None)
    with db.cursor() as sql:
        db.set_seat(sql, '500111111', '9', TUE)
    with db.cursor() as sql:
        seats = dict(sql.execute(
            'select id, seat from requests where id in (?, ?)', (tue, wed)
        ).fetchall())
    assert seats[tue] == '9'
    assert seats[wed] is None


# --- through the routes, end to end --------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_join_books_the_chosen_session(db, monkeypatch):
    """A student picks a future session; the request lands on that day, seatless."""
    monkeypatch.setattr(logic, 'upcoming_studios',
                        lambda *a, **k: [TUE, WED, '2026-07-30'])
    client = signed_in_as('500111111', 'student')
    client.post('/queue/join', data={'competency_ids': ['1'], 'studio_date': WED})
    with db.cursor() as sql:
        row = sql.execute(
            "select studio_date, seat, status from requests where student_number = ?",
            ('500111111',)
        ).fetchone()
    assert row == (WED, None, 'waiting')


def test_join_rejects_a_non_studio_date(db, monkeypatch):
    """A hand-crafted date that is not an offered session falls back, never inserts as-is."""
    monkeypatch.setattr(logic, 'upcoming_studios',
                        lambda *a, **k: [TUE, WED])
    monkeypatch.setattr(logic, 'next_studio', lambda *a, **k: TUE)
    client = signed_in_as('500111111', 'student')
    client.post('/queue/join', data={'competency_ids': ['1'], 'studio_date': '2026-07-31'})
    with db.cursor() as sql:
        booked = sql.execute(
            "select studio_date from requests where student_number = ?", ('500111111',)
        ).fetchone()[0]
    assert booked == TUE  # fell back to next_studio, not the bogus Friday


def test_future_session_is_a_read_only_planning_roster(db, monkeypatch):
    """A seatless future booking shows in that day's planning view but is not claimable."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 27))  # Monday
    monkeypatch.setattr(logic, 'upcoming_studios', lambda *a, **k: [TUE, WED])
    book('500111111', 1, TUE, seat=None)  # booked ahead, no seat
    body = signed_in_as('dmason', 'staff').get(
        '/queue?day=' + TUE).get_data(as_text=True)
    assert 'Chen, Alice' in body          # the booking is visible
    assert 'booked' in body               # shown as booked, not a seat
    assert 'queue_claim' not in body      # but there is no claim action
