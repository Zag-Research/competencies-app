"""Attendance (#attendance): self check-in, independent of seat and competencies."""
import sqlite3
from datetime import date

import pytest

import db as db_module
import logic

TUE = '2026-07-28'   # a real studio day
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
        sql.execute("insert into students values ('Ben', 'Okafor', '500222222')")
        sql.execute("insert into competencies (id, name) values (1, 'Nested loops')")
    return db_module


def count_for(student_number):
    with db_module.cursor() as sql:
        return sql.execute(
            'select count(*) from attendance where student_number = ?',
            (student_number,)
        ).fetchone()[0]


# --- the check-in record -------------------------------------------------

def test_marking_present_records_attendance(db):
    with db.cursor() as sql:
        db.mark_present(sql, '500111111', TUE)
        assert db.is_present(sql, '500111111', TUE) is True
    assert count_for('500111111') == 1


def test_checking_in_twice_the_same_day_is_a_no_op(db):
    with db.cursor() as sql:
        db.mark_present(sql, '500111111', TUE)
        db.mark_present(sql, '500111111', TUE)
    assert count_for('500111111') == 1


def test_attendance_is_per_session(db):
    with db.cursor() as sql:
        db.mark_present(sql, '500111111', TUE)
        db.mark_present(sql, '500111111', WED)
    assert count_for('500111111') == 2


def test_counts_rank_by_sessions_attended(db):
    with db.cursor() as sql:
        db.mark_present(sql, '500111111', TUE)
        db.mark_present(sql, '500111111', WED)
        db.mark_present(sql, '500222222', TUE)
        counts = db.attendance_counts(sql)
    assert counts == [('Alice', 'Chen', 2), ('Ben', 'Okafor', 1)]


def test_day_roster_lists_who_was_present(db):
    with db.cursor() as sql:
        db.mark_present(sql, '500222222', TUE)
        roster = db.attendance_for_day(sql, TUE)
    assert roster == [('Ben', 'Okafor')]  # (first_name, last_name)


# --- through the routes --------------------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_taking_a_seat_records_attendance_without_signing_up(db, monkeypatch):
    """Since the "I'm here today" button was removed (#46), the seat IS the check-in.

    A student who came to the studio to work rather than be evaluated still needs to
    be counted present, so entering a seat records attendance on its own, with nothing
    booked for the session.
    """
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))  # Tuesday
    signed_in_as('500111111', 'student').post('/queue/seat', data={'seat': '12'})
    assert count_for('500111111') == 1


def test_the_removed_checkin_endpoint_is_gone(db, monkeypatch):
    """The old route must not linger: one writer of attendance, not two (#46)."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    response = signed_in_as('500111111', 'student').post('/queue/checkin')
    assert response.status_code == 404
    assert count_for('500111111') == 0


def test_taking_a_seat_also_marks_present(db, monkeypatch):
    """A student who signs up and takes a seat should not have to check in twice."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    monkeypatch.setattr(logic, 'upcoming_studios', lambda *a, **k: [TUE, WED])
    client = signed_in_as('500111111', 'student')
    client.post('/queue/join', data={'competency_ids': ['1'], 'studio_date': TUE})
    client.post('/queue/seat', data={'seat': '12'})
    assert count_for('500111111') == 1


def test_seat_on_a_non_studio_day_does_not_mark_present(db, monkeypatch):
    """A crafted seat POST on a non-class day must not inflate the attended count."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 25))  # Saturday
    signed_in_as('500111111', 'student').post('/queue/seat', data={'seat': 'hax'})
    assert count_for('500111111') == 0


def test_a_student_cannot_be_marked_present_by_someone_else(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    # Staff hitting the student seat endpoint records nothing for any student.
    signed_in_as('dmason', 'staff').post('/queue/seat', data={'seat': '12'})
    assert count_for('500111111') == 0
    assert count_for('500222222') == 0


def test_attendance_page_is_staff_only(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    with db.cursor() as sql:
        db.mark_present(sql, '500111111', TUE)
    staff = signed_in_as('dmason', 'staff')
    body = staff.get('/attendance').get_data(as_text=True)
    assert 'Chen, Alice' in body
    student = signed_in_as('500111111', 'student')
    assert student.get('/attendance').status_code == 302
