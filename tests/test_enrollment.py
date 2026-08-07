"""Per-course filtering (#11): a part-time student sees only their course."""
import sqlite3

import pytest

import db as db_module


@pytest.fixture
def db(tmp_path, monkeypatch):
    """CPS109 competency (id 1), CPS213 competency (id 2), and three students:
    Alice in both, Chloe part-time in CPS109, Dana with no enrollment recorded."""
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
        sql.execute("insert into students values ('Chloe', 'Diaz', '500333333')")
        sql.execute("insert into students values ('Dana', 'Ng', '500444444')")
        sql.execute("insert into competencies (id, name, course) values (1, 'Nested loops', 'CPS109')")
        sql.execute("insert into competencies (id, name, course) values (2, 'Latches', 'CPS213')")
        sql.execute("insert into enrollments values ('500111111', 'CPS109')")
        sql.execute("insert into enrollments values ('500111111', 'CPS213')")
        sql.execute("insert into enrollments values ('500333333', 'CPS109')")
    return db_module


def course_ids(rows):
    return {row[0] for row in rows}


def test_full_time_student_sees_both_courses(db):
    with db.cursor() as sql:
        rows = db.competencies_for(sql, '500111111')
    assert course_ids(rows) == {1, 2}


def test_part_time_student_sees_only_their_course(db):
    with db.cursor() as sql:
        rows = db.competencies_for(sql, '500333333')
    assert course_ids(rows) == {1}  # CPS109 only, not the CPS213 latch


def test_unenrolled_student_sees_everything(db):
    """No enrollment rows must not mean a blank page: they see all competencies."""
    with db.cursor() as sql:
        rows = db.competencies_for(sql, '500444444')
    assert course_ids(rows) == {1, 2}


def test_enrolled_courses_lists_them(db):
    with db.cursor() as sql:
        assert db.enrolled_courses(sql, '500111111') == ['CPS109', 'CPS213']
        assert db.enrolled_courses(sql, '500333333') == ['CPS109']
        assert db.enrolled_courses(sql, '500444444') == []


# --- through the routes --------------------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_part_time_progress_page_hides_the_other_course(db):
    body = signed_in_as('500333333', 'student').get(
        '/view/500333333').get_data(as_text=True)
    assert 'Nested loops' in body    # CPS109, enrolled
    assert 'Latches' not in body     # CPS213, not enrolled


def test_part_time_student_cannot_book_the_other_course(db):
    """A crafted POST for a non-enrolled competency books nothing."""
    signed_in_as('500333333', 'student').post(
        '/queue/join', data={'competency_ids': ['2'], 'studio_date': '2026-07-28'})
    with db.cursor() as sql:
        booked = sql.execute(
            "select count(*) from requests where student_number = '500333333'"
        ).fetchone()[0]
    assert booked == 0  # competency 2 is CPS213, which Chloe is not taking
