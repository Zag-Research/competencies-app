"""Where a student is sitting has to survive being said before they book (#83).

The seat used to live only on `requests` rows. That is fine for the order the app was
built around, book first and sit down later, and wrong for the other one: a student who
taps "I am here" on arriving and then decides what to demonstrate had no request for the
seat to land on. It was dropped, the screen said a TA would come to them, and no TA
could see them, because the staff queue only lists requests that carry a seat.
"""
import sqlite3
from datetime import date

import pytest

import db as db_module
import logic

DAY = date(2026, 9, 22)          # a Tuesday in term
STUDENT = '500111111'


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
    monkeypatch.setattr(logic, 'today_toronto', lambda: DAY)
    with db_module.cursor() as sql:
        sql.execute("insert into students values ('Alice', 'Chen', ?)", (STUDENT,))
        sql.execute("insert into competencies (id, name, course)"
                    " values (1, 'Nested ifs', 'CPS109')")
        sql.execute("insert into enrollments (student_number, course)"
                    " values (?, 'CPS109')", (STUDENT,))
    return db_module


def as_student():
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'], s['role'] = STUDENT, 'student'
    return client


def sit_down(client, seat='12'):
    return client.post('/queue/seat', data={'seat': seat})


def book(client, competency_id=1, day=None):
    return client.post('/queue/join', data={
        'competency_ids': str(competency_id),
        'studio_date': (day or DAY).isoformat()})


def request_seat(sql):
    row = sql.execute("select seat from requests where student_number = ?",
                      (STUDENT,)).fetchone()
    return row[0] if row else None


def on_the_live_queue(sql):
    """The staff queue only shows requests that carry a seat: there is nowhere to walk."""
    return sql.execute(
        "select count(*) from requests where student_number = ? and studio_date = ?"
        "   and seat is not null and seat != '' and status = 'waiting'",
        (STUDENT, DAY.isoformat())).fetchone()[0] > 0


def test_booking_first_then_sitting_down_works(db):
    client = as_student()
    book(client)
    sit_down(client)
    with db.cursor() as sql:
        assert request_seat(sql) == '12'
        assert on_the_live_queue(sql)


def test_sitting_down_first_then_booking_works_too(db):
    """The regression. This is the order a student who arrives early actually uses."""
    client = as_student()
    sit_down(client)
    book(client)
    with db.cursor() as sql:
        assert request_seat(sql) == '12'
        assert on_the_live_queue(sql), (
            'booked after sitting down and never reached the staff queue, '
            'having been told a TA was on the way')


def test_sitting_down_with_nothing_booked_still_records_the_seat(db):
    client = as_student()
    sit_down(client, '14')
    with db.cursor() as sql:
        assert db.seat_for(sql, STUDENT, DAY.isoformat()) == '14'
        assert db.is_present(sql, STUDENT, DAY.isoformat())


def test_moving_machines_updates_both_places(db):
    client = as_student()
    sit_down(client, '12')
    book(client)
    sit_down(client, '30')
    with db.cursor() as sql:
        assert request_seat(sql) == '30'
        assert db.seat_for(sql, STUDENT, DAY.isoformat()) == '30'


def test_leaving_clears_the_seat_but_not_attendance(db):
    """An empty seat means gone. They were still here, so it does not un-attend them."""
    client = as_student()
    sit_down(client, '12')
    book(client)
    sit_down(client, '')
    with db.cursor() as sql:
        assert request_seat(sql) is None
        assert db.seat_for(sql, STUDENT, DAY.isoformat()) is None
        assert not on_the_live_queue(sql)
        assert db.is_present(sql, STUDENT, DAY.isoformat())


def test_a_future_booking_does_not_inherit_todays_seat(db):
    """Sitting down today says nothing about next Tuesday."""
    client = as_student()
    sit_down(client, '12')
    book(client, day=date(2026, 9, 29))
    with db.cursor() as sql:
        seats = [row[0] for row in sql.execute(
            "select seat from requests where student_number = ? and studio_date = ?",
            (STUDENT, '2026-09-29'))]
    assert seats == [None]


def test_a_seat_on_a_non_studio_day_records_nothing(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 9, 26))  # Saturday
    sit_down(as_student(), '12')
    with db.cursor() as sql:
        assert not db.is_present(sql, STUDENT, '2026-09-26')
        assert db.seat_for(sql, STUDENT, '2026-09-26') is None
