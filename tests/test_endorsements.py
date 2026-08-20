"""Peer helpfulness (#20): the once-per-day rule, the tally, and the routes."""
import sqlite3

import pytest

import db as db_module
import logic

# A fixed calendar day for the db-level tests.
DAY = '2026-07-28'


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
        assert db.add_endorsement(sql, '500111111', '500222222', DAY) is True
    assert received_count('500222222') == 1


def test_second_thank_you_same_day_is_ignored(db):
    with db.cursor() as sql:
        assert db.add_endorsement(sql, '500111111', '500222222', DAY) is True
        assert db.add_endorsement(sql, '500111111', '500222222', DAY) is False
    # Still one: a repeat tap cannot inflate the count.
    assert received_count('500222222') == 1


def test_two_different_students_can_thank_the_same_person(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222', DAY)
        db.add_endorsement(sql, '500333333', '500222222', DAY)
    assert received_count('500222222') == 2


def test_a_student_cannot_thank_themselves(db):
    with db.cursor() as sql:
        assert db.add_endorsement(sql, '500111111', '500111111', DAY) is False
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
        db.add_endorsement(sql, '500111111', '500222222', DAY)
        given = db.endorsements_given_today(sql, '500111111', DAY)
    assert given == [('Ben', 'Okafor')]


def test_tally_reports_both_the_total_and_how_many_people(db):
    with db.cursor() as sql:
        db.add_endorsement(sql, '500111111', '500222222', DAY)
        db.add_endorsement(sql, '500333333', '500222222', DAY)
        db.add_endorsement(sql, '500222222', '500333333', DAY)
        tallies = db.endorsement_tallies(sql)
    # Ben: 2 thank-yous from 2 people. Chloe: 1 from 1. Alice, thanked by nobody, absent.
    assert tallies == [('Ben', 'Okafor', 2, 2), ('Chloe', 'Diaz', 1, 1)]


def test_a_reciprocal_pair_is_distinguishable_from_being_helpful(db):
    """The gaming this exists to make visible.

    Alice and Ben thank each other every session. Over three days each ends on three,
    which the total alone cannot tell apart from being thanked three times by three
    different classmates. The second number can: theirs is 1.
    """
    days = ['2026-07-28', '2026-07-29', '2026-07-30']
    with db.cursor() as sql:
        sql.execute("insert into students values ('Dana', 'Ng', '500444444')")
        for day in days:
            db.add_endorsement(sql, '500111111', '500222222', day)   # Alice -> Ben
            db.add_endorsement(sql, '500222222', '500111111', day)   # Ben -> Alice
        # Dana was thanked three times, by three different people.
        for giver in ('500111111', '500222222', '500333333'):
            db.add_endorsement(sql, giver, '500444444', days[0])
        tallies = db.endorsement_tallies(sql)
    by_name = {last: (n, people) for (_f, last, n, people) in tallies}
    assert by_name['Okafor'] == (3, 1)      # three thank-yous, one person
    assert by_name['Ng'] == (3, 3)          # three thank-yous, three people
    # Breadth decides the order, so Dana is above the reciprocal pair.
    assert tallies[0][1] == 'Ng' 


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
        db.add_endorsement(sql, '500111111', '500222222', DAY)
    staff = signed_in_as('dmason', 'staff')
    body = staff.get('/endorsements').get_data(as_text=True)
    assert 'Okafor, Ben' in body
    # A student is redirected away rather than shown the tally.
    student = signed_in_as('500111111', 'student')
    assert student.get('/endorsements').status_code == 302


def test_endorse_stamps_the_toronto_day_not_utc(db, monkeypatch):
    """The stored day must come from Toronto time, not the DB's UTC date('now').

    The bug: with SQL date('now') (UTC), an evening thank-you gets stamped with
    tomorrow's date, so the once-per-day rule misses a same-evening re-tap. Pinning
    'today' to a known Toronto date and checking the stored day catches a regression.
    """
    from datetime import date
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    signed_in_as('500111111', 'student').post(
        '/endorse', data={'to_student': '500222222'})
    with db.cursor() as sql:
        stored_day = sql.execute(
            "select day from endorsements where from_student = '500111111'"
        ).fetchone()[0]
    assert stored_day == '2026-07-28'
