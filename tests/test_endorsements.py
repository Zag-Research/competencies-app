"""Peer helpfulness (#20): the once-per-day rule, the tally, and the routes."""
import sqlite3

import pytest

import db as db_module


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh database with three students."""
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
        sql.execute("insert into students values ('Chloe', 'Diaz', '500333333')")
    return db_module


def received_count(to_student):
    with db_module.cursor() as sql:
        row = sql.execute(
            'select count(*) from endorsements where to_student = ?', (to_student,)
        ).fetchone()
    return row[0]


# --- the record + the once-per-day rule ----------------------------------

def test_a_thank_you_is_recorded(db):
    with db.cursor() as sql:
        assert db.add_endorsement(sql, '500111111', '500222222') is True
    assert received_count('500222222') == 1


def test_second_thank_you_same_day_is_ignored(db):
    with db.cursor() as sql:
        assert db.add_endorsement(sql, '500111111', '500222222') is True
        assert db.add_endorsement(sql, '500111111', '500222222') is False
    # Still one: a repeat tap cannot inflate the count.
    assert received_count('500222222') == 1


def test_two_different_students_can_thank_the_same_person(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222')
        db.add_endorsement(sql, '500333333', '500222222')
    assert received_count('500222222') == 2


def test_a_student_cannot_thank_themselves(db):
    with db.cursor() as sql:
        assert db.add_endorsement(sql, '500111111', '500111111') is False
    assert received_count('500111111') == 0


# --- the reads the pages rely on -----------------------------------------

def test_classmates_excludes_self(db):
    with db.cursor() as sql:
        mates = db.classmates(sql, '500111111')
    numbers = [row[0] for row in mates]
    assert '500111111' not in numbers
    assert set(numbers) == {'500222222', '500333333'}


def test_given_today_lists_who_you_thanked(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222')
        given = db.endorsements_given_today(sql, '500111111')
    assert given == [('Ben', 'Okafor')]


def test_tally_counts_and_orders_by_most_thanked(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222')
        db.add_endorsement(sql, '500333333', '500222222')
        db.add_endorsement(sql, '500222222', '500333333')
        tallies = db.endorsement_tallies(sql)
    # Ben (2) ahead of Chloe (1); Alice, thanked by nobody, absent.
    assert tallies == [('Ben', 'Okafor', 2), ('Chloe', 'Diaz', 1)]


# --- routes --------------------------------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_endorse_route_records_and_returns_to_own_page(db):
    client = signed_in_as('500111111', 'student')
    response = client.post('/endorse', data={'to_student': '500222222'})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/view/500111111')
    assert received_count('500222222') == 1


def test_endorse_route_ignores_an_empty_pick(db):
    client = signed_in_as('500111111', 'student')
    client.post('/endorse', data={'to_student': ''})
    with db.cursor() as sql:
        total = sql.execute('select count(*) from endorsements').fetchone()[0]
    assert total == 0


def test_endorse_route_rejects_a_self_pick(db):
    client = signed_in_as('500111111', 'student')
    client.post('/endorse', data={'to_student': '500111111'})
    assert received_count('500111111') == 0


def test_staff_cannot_endorse(db):
    client = signed_in_as('dmason', 'staff')
    client.post('/endorse', data={'to_student': '500222222'})
    assert received_count('500222222') == 0


def test_tally_page_is_staff_only(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222')
    staff = signed_in_as('dmason', 'staff')
    body = staff.get('/endorsements').get_data(as_text=True)
    assert 'Okafor, Ben' in body
    # A student is redirected away rather than shown the tally.
    student = signed_in_as('500111111', 'student')
    assert student.get('/endorsements').status_code == 302
