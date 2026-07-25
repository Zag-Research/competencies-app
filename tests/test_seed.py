"""The real seed data loads, is tagged by course, and the pages render on it."""
import sqlite3

import pytest

import db as db_module


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A database built from the actual schema.sql + seed.sql."""
    path = tmp_path / 'seeded.db'
    connection = sqlite3.connect(path)
    with open('schema.sql') as f:
        connection.executescript(f.read())
    with open('seed.sql') as f:
        connection.executescript(f.read())
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    return db_module


def test_both_courses_are_seeded_forty_each(seeded):
    with seeded.cursor() as sql:
        counts = dict(sql.execute(
            "select course, count(*) from competencies group by course"
        ).fetchall())
    assert counts == {'CPS109': 40, 'CPS213': 40}


def test_every_competency_has_a_course(seeded):
    with seeded.cursor() as sql:
        orphans = sql.execute(
            "select count(*) from competencies where course is null or course = ''"
        ).fetchone()[0]
    assert orphans == 0


def test_the_math_library_fix_is_in(seeded):
    with seeded.cursor() as sql:
        row = sql.execute(
            "select name from competencies where id = 2"
        ).fetchone()
    assert 'math library' in row[0]
    assert 'max library' not in row[0]


def test_apostrophes_survived_seeding(seeded):
    # DeMorgan's etc. go in through doubled quotes; make sure they read back whole.
    with seeded.cursor() as sql:
        hits = sql.execute(
            "select count(*) from competencies where name like '%DeMorgan''s%'"
        ).fetchone()[0]
    assert hits >= 2


def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_student_progress_page_groups_by_course(seeded):
    client = signed_in_as('500111111', 'student')
    body = client.get('/view/500111111').get_data(as_text=True)
    assert 'CPS109' in body
    assert 'CPS213' in body


def test_mark_page_renders_all_eighty(seeded):
    client = signed_in_as('dmason', 'staff')
    body = client.get('/mark/500111111').get_data(as_text=True)
    assert 'CPS109' in body and 'CPS213' in body
    # A CPS213 competency title should appear, proving the second block rendered.
    assert 'Register Circuit' in body


def test_evaluation_screen_shows_the_competency_scope(seeded):
    """A TA evaluating sees the sub-points, not just the competency title."""
    with seeded.cursor() as sql:
        # Competency 41 is CPS213 "Understands different numbering systems".
        sql.execute(
            """insert into requests
                   (student_number, competency_id, seat, requested_at, status, studio_date)
               values ('500111111', 41, '12', CURRENT_TIMESTAMP, 'waiting', '2026-07-28')"""
        )
        seeded.claim_student(sql, '500111111', 'dmason', '2026-07-28')
    body = signed_in_as('dmason', 'staff').get(
        '/queue/student/500111111').get_data(as_text=True)
    assert 'Understands different numbering systems' in body
    # The scope from the source document's sub-points.
    assert 'Hexadecimal' in body
    assert 'competency-scope' in body
