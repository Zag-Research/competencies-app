"""The per-evaluator report (#49): is the evaluation load actually being shared?"""
import sqlite3

import pytest

import db as db_module
import logic


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Two students and two competencies; dmason/lfortune are staff via schema.sql."""
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


def evaluated(student_number, competency_id, by, when, status='achieved'):
    """One evaluation event, the way record_achievement appends them."""
    with db_module.cursor() as sql:
        sql.execute(
            "insert into evaluations "
            "(student_number, competency_id, status, recorded_at, evaluated_by) "
            "values (?, ?, ?, ?, ?)",
            (student_number, competency_id, status, when, by)
        )


def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


# --- the counts ------------------------------------------------------------

def test_counts_are_per_evaluator(db):
    evaluated('500111111', 1, 'dmason', '2026-09-15 10:00')
    evaluated('500222222', 1, 'dmason', '2026-09-15 10:05')
    evaluated('500111111', 2, 'lfortune', '2026-09-15 10:10')
    with db.cursor() as sql:
        assert db.evaluator_counts(sql) == {'dmason': 2, 'lfortune': 1}


def test_a_fail_counts_as_much_as_a_pass(db):
    """Recording 'not passed' is the same work, and this page measures work."""
    evaluated('500111111', 1, 'dmason', '2026-09-15 10:00', status='cooling_off')
    with db.cursor() as sql:
        assert db.evaluator_counts(sql) == {'dmason': 1}


def test_since_narrows_to_recent_work(db):
    evaluated('500111111', 1, 'dmason', '2026-09-01 10:00')   # older
    evaluated('500222222', 1, 'dmason', '2026-09-20 10:00')   # recent
    with db.cursor() as sql:
        assert db.evaluator_counts(sql, since='2026-09-15') == {'dmason': 1}
        assert db.evaluator_counts(sql) == {'dmason': 2}


def test_a_retry_counts_for_both_tas(db):
    """The reason this counts events rather than results.

    Alice fails nested loops with lfortune, then passes it with dmason. One
    competency, one final result, but two evaluations and two people who did one.
    """
    evaluated('500111111', 1, 'lfortune', '2026-09-15 10:00', status='cooling_off')
    evaluated('500111111', 1, 'dmason', '2026-09-17 10:00', status='achieved')
    with db.cursor() as sql:
        assert db.evaluator_counts(sql) == {'lfortune': 1, 'dmason': 1}


def test_days_ago_counts_back_from_today():
    from datetime import date
    assert logic.days_ago(7, today=date(2026, 9, 20)) == '2026-09-13'


# --- the page --------------------------------------------------------------

def test_the_page_lists_evaluators_with_their_totals(db):
    evaluated('500111111', 1, 'dmason', '2026-09-15 10:00')
    body = signed_in_as('dmason', 'staff').get('/evaluators').get_data(as_text=True)
    assert 'dmason' in body
    assert '1 total' in body


def test_the_page_says_so_when_nothing_is_recorded(db):
    body = signed_in_as('dmason', 'staff').get('/evaluators').get_data(as_text=True)
    assert 'No evaluations recorded yet' in body


def test_students_cannot_see_who_evaluated_whom(db):
    """Staff-only: this is about TA workload, not a student's business."""
    response = signed_in_as('500111111', 'student').get('/evaluators')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']
