"""The per-session sign-up rule (#22): a cap, and the two courses within 1 apart."""
import sqlite3

import pytest

import db as db_module
import logic

CAP = 3


def counts(cps109, cps213):
    return {'CPS109': cps109, 'CPS213': cps213}


def test_two_and_one_is_allowed():
    assert logic.session_signup_ok(counts(2, 1), CAP) is True


def test_an_even_split_is_allowed():
    assert logic.session_signup_ok(counts(1, 1), CAP) is True


def test_three_and_zero_breaks_the_balance():
    assert logic.session_signup_ok(counts(3, 0), CAP) is False


def test_two_and_zero_breaks_the_balance():
    # 2 ahead of 0 is a gap of 2, not allowed even though it is under the cap.
    assert logic.session_signup_ok(counts(2, 0), CAP) is False


def test_over_the_cap_is_rejected():
    # 2 + 2 = 4 is perfectly balanced but too many for a 3-cap session.
    assert logic.session_signup_ok(counts(2, 2), CAP) is False


def test_a_single_course_only_hits_the_cap():
    # A student with one course has nothing to balance against, so only the cap
    # applies (the finished-a-course case would reduce to this once handled).
    assert logic.session_signup_ok({'CPS109': 3}, CAP) is True
    assert logic.session_signup_ok({'CPS109': 4}, CAP) is False


# --- the rule wired into real sign-up ------------------------------------

STUDIO = '2026-07-28'   # a Tuesday


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Alice, enrolled in both courses, with 3 CPS109 and 3 CPS213 competencies."""
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
        for i in (1, 2, 3):
            sql.execute("insert into competencies (id, name, course)"
                        " values (?, ?, 'CPS109')", (i, 'py' + str(i)))
        for i in (4, 5, 6):
            sql.execute("insert into competencies (id, name, course)"
                        " values (?, ?, 'CPS213')", (i, 'logic' + str(i)))
        sql.execute("insert into enrollments values ('500111111', 'CPS109')")
        sql.execute("insert into enrollments values ('500111111', 'CPS213')")
    return db_module


def student_client(monkeypatch):
    monkeypatch.setattr(logic, 'upcoming_studios', lambda *a, **k: [STUDIO])
    import app as app_module
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    return c


def booked_count():
    with db_module.cursor() as sql:
        return sql.execute(
            "select count(*) from requests where student_number = '500111111'"
        ).fetchone()[0]


def test_a_balanced_signup_is_accepted(db, monkeypatch):
    # 2 CPS109 (ids 1,2) + 1 CPS213 (id 4): balanced, at the cap.
    student_client(monkeypatch).post(
        '/queue/join', data={'competency_ids': ['1', '2', '4'], 'studio_date': STUDIO})
    assert booked_count() == 3


def test_a_lopsided_signup_is_rejected_whole(db, monkeypatch):
    # 3 CPS109, 0 CPS213: breaks the balance, so NONE of it is booked.
    student_client(monkeypatch).post(
        '/queue/join', data={'competency_ids': ['1', '2', '3'], 'studio_date': STUDIO})
    assert booked_count() == 0


def test_cannot_edge_past_balance_across_two_signups(db, monkeypatch):
    # The rule looks at the whole session, not one click: 1 CPS109 now is fine,
    # but a second CPS109 later (2 and 0) is rejected.
    c = student_client(monkeypatch)
    c.post('/queue/join', data={'competency_ids': ['1'], 'studio_date': STUDIO})
    assert booked_count() == 1
    c.post('/queue/join', data={'competency_ids': ['2'], 'studio_date': STUDIO})
    assert booked_count() == 1   # second one rejected; still just the first
