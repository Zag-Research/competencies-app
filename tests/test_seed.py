"""The real seed data loads, is tagged by course, and the pages render on it."""
import sqlite3

import pytest

import db as db_module


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A database built the way local development is: schema, competencies, samples."""
    path = tmp_path / 'seeded.db'
    connection = sqlite3.connect(path)
    for name in ('schema.sql', 'competencies.sql', 'seed.sql'):
        with open(name) as f:
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


# --- the production load path (#92) -----------------------------------------

def production_db(tmp_path):
    """What a real deployment loads: schema and the real competency list. No people."""
    path = tmp_path / 'production.db'
    connection = sqlite3.connect(path)
    for name in ('schema.sql', 'competencies.sql'):
        with open(name) as f:
            connection.executescript(f.read())
    connection.commit()
    return connection


def test_the_competency_file_carries_the_real_list(tmp_path):
    connection = production_db(tmp_path)
    counts = dict(connection.execute(
        "select course, count(*) from competencies group by course"))
    assert counts == {'CPS109': 40, 'CPS213': 40}


def test_the_competency_file_contains_no_people(tmp_path):
    """The whole point of the split.

    seed.sql mixes five invented students, their results and sample coverage pairs in
    with the real competency list. Loading that on a real deployment would enrol
    students who do not exist and credit TAs with evaluations they never did, and
    nothing about it would error. Production loads this file instead.
    """
    connection = production_db(tmp_path)
    for table in ('students', 'enrollments', 'achievements', 'evaluations',
                  'attendance', 'endorsements', 'competency_covers', 'requests'):
        n = connection.execute('select count(*) from ' + table).fetchone()[0]
        assert n == 0, '%s is not empty in the production load path' % table


def test_the_sample_file_still_says_it_is_samples(tmp_path):
    """A comment is the only thing stopping somebody running the wrong file."""
    head = open('seed.sql').read()[:400].upper()
    assert 'LOCAL DEVELOPMENT' in head
    assert 'NEVER LOAD THIS INTO PRODUCTION' in head


def test_the_marking_page_shows_what_a_competency_covers(seeded):
    """A TA marking saw only the name. The queue screens already showed the sub-points;
    the marking page, where the judgement is actually recorded, did not (#112).
    """
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'], s['role'] = 'dmason', 'staff'
    body = client.get('/mark/500111111').get_data(as_text=True)
    assert 'competency-scope' in body
    assert 'Uses an if statement for conditional commands' in body


def test_a_competency_with_no_sub_points_adds_no_empty_list(seeded):
    """32 of the 80 have no description yet, and an empty bullet list under a name
    would be worse than nothing."""
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'], s['role'] = 'dmason', 'staff'
    body = client.get('/mark/500111111').get_data(as_text=True)
    row = body.split('Uses variables with meaningful naming conventions')[1][:300]
    assert 'competency-scope' not in row
