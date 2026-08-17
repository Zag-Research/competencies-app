"""Who evaluated whom (#48), recorded identically by both marking screens (#44).

Dave settled #44 with "both should stay, but be consistent", so the interesting
assertions here are the ones that run the *same* check against both screens: if
the two ever drift apart, these fail.
"""
import sqlite3

import pytest

import db as db_module


@pytest.fixture
def db(tmp_path, monkeypatch):
    """One student, two competencies, and dmason/lfortune as staff (from schema.sql)."""
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


def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def evaluator_of(competency_id, student_number='500111111'):
    with db_module.cursor() as sql:
        row = sql.execute(
            'select evaluated_by from achievements '
            'where student_number = ? and competency_id = ?',
            (student_number, competency_id)
        ).fetchone()
    return row[0] if row else None


def claimed_request(student_number, competency_id, claimed_by):
    """A request already claimed by an evaluator, ready to be marked."""
    with db_module.cursor() as sql:
        sql.execute(
            """insert into requests
                   (student_number, competency_id, seat, requested_at, status,
                    claimed_by, claimed_at, studio_date)
               values (?, ?, '12', CURRENT_TIMESTAMP, 'claimed', ?,
                       CURRENT_TIMESTAMP, '2026-07-28')""",
            (student_number, competency_id, claimed_by)
        )
        return sql.lastrowid


# --- both screens record the evaluator -----------------------------------

def test_the_mark_page_records_who_marked_it(db):
    signed_in_as('dmason', 'staff').post('/save/500111111/1/achieved')
    assert evaluator_of(1) == 'dmason'


def test_the_queue_screen_records_who_marked_it(db):
    rid = claimed_request('500111111', 2, 'lfortune')
    signed_in_as('lfortune', 'staff').post('/queue/mark/%d/achieved' % rid)
    assert evaluator_of(2) == 'lfortune'


def test_the_two_screens_agree(db):
    """#44: the same evaluation through either screen leaves the same record."""
    signed_in_as('dmason', 'staff').post('/save/500111111/1/achieved')
    rid = claimed_request('500111111', 2, 'dmason')
    signed_in_as('dmason', 'staff').post('/queue/mark/%d/achieved' % rid)
    with db_module.cursor() as sql:
        rows = sql.execute(
            'select status, evaluated_by from achievements order by competency_id'
        ).fetchall()
    assert rows[0] == rows[1]


def test_the_evaluator_is_whoever_finished_it_not_whoever_claimed_it(db):
    """A competency handed on after a decline (#19) belongs to the TA who did it."""
    rid = claimed_request('500111111', 2, 'lfortune')   # lfortune claimed it
    with db_module.cursor() as sql:                     # then it moved to dmason
        sql.execute("update requests set claimed_by = 'dmason' where id = ?", (rid,))
    signed_in_as('dmason', 'staff').post('/queue/mark/%d/achieved' % rid)
    assert evaluator_of(2) == 'dmason'


# --- undo leaves no trace of an evaluator --------------------------------

def test_undoing_a_mark_page_tap_removes_the_evaluator_too(db):
    client = signed_in_as('dmason', 'staff')
    client.post('/save/500111111/1/achieved')
    client.post('/save/500111111/1/unassessed')
    assert evaluator_of(1) is None


def test_undoing_a_queue_mark_removes_the_evaluator_too(db):
    rid = claimed_request('500111111', 2, 'dmason')
    client = signed_in_as('dmason', 'staff')
    client.post('/queue/mark/%d/achieved' % rid)
    client.post('/queue/undo/%d' % rid)
    assert evaluator_of(2) is None


# --- the guard that was already there still holds ------------------------

def test_a_student_still_cannot_write_their_own_result(db):
    signed_in_as('500111111', 'student').post('/save/500111111/1/achieved')
    assert evaluator_of(1) is None
