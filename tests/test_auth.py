"""Authorization guards: who is allowed to mark, and to view whose progress.

These pin the fixes for the three holes found in the Monday quality sweep:
- /save wrote achievements with no auth at all (a student could self-mark).
- /mark opened the staff marking screen to anyone.
- /view let a student read a classmate's grades.
"""
import sqlite3

import pytest

import db as db_module


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
        sql.execute("insert into competencies (id, name, course) values (1, 'Nested loops', 'CPS109')")
    return db_module


def client_as(username, role):
    import app as app_module
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return c


def anon_client():
    import app as app_module
    return app_module.app.test_client()


def achievement_count():
    with db_module.cursor() as sql:
        return sql.execute('select count(*) from achievements').fetchone()[0]


# --- /save must be staff-only (was: no auth at all) ----------------------

def test_student_cannot_self_mark_via_save(db):
    """The critical one: a student POSTing their own competency to achieved."""
    resp = client_as('500111111', 'student').post('/save/500111111/1/achieved')
    assert resp.status_code == 403
    assert achievement_count() == 0


def test_anonymous_cannot_save(db):
    resp = anon_client().post('/save/500111111/1/achieved')
    assert resp.status_code == 403
    assert achievement_count() == 0


def test_staff_can_save(db):
    resp = client_as('dmason', 'staff').post('/save/500111111/1/achieved')
    assert resp.status_code == 200
    assert achievement_count() == 1


def test_save_rejects_an_unknown_state(db):
    """/save writes straight to achievements, so it must refuse junk status text."""
    resp = client_as('dmason', 'staff').post('/save/500111111/1/hacked')
    assert resp.status_code == 400
    assert achievement_count() == 0


# --- /mark must be staff-only --------------------------------------------

def test_student_cannot_open_the_mark_page(db):
    resp = client_as('500111111', 'student').get('/mark/500111111')
    assert resp.status_code == 302  # redirected to login, not shown


def test_staff_can_open_the_mark_page(db):
    resp = client_as('dmason', 'staff').get('/mark/500111111')
    assert resp.status_code == 200


# --- /view: a student sees only their own progress -----------------------

def test_student_cannot_view_a_classmates_progress(db):
    c = client_as('500111111', 'student')
    resp = c.get('/view/500222222')  # Ben's page
    assert resp.status_code == 302
    # Bounced back to their own page, not shown Ben's.
    assert resp.headers['Location'].endswith('/view/500111111')


def test_student_can_view_their_own_progress(db):
    resp = client_as('500111111', 'student').get('/view/500111111')
    assert resp.status_code == 200


def test_staff_can_view_any_student(db):
    resp = client_as('dmason', 'staff').get('/view/500222222')
    assert resp.status_code == 200


# --- production identity comes from the TMU CAS header --------------------

def test_identity_from_cas_resolves_staff_students_and_unknowns(db):
    """CAS sends two things and the app needs both.

    Cas-User is the TMU username, which is the whole answer for staff. The student
    number arrives as a separate attribute header, and it is a different string from
    the username, so a student resolves from that one.
    """
    import common
    # Staff: the CAS username is already the admin key, no attribute needed.
    assert common.identity_from_cas('dmason') == ('dmason', 'staff')
    # Student: resolved from the attribute, not from their username.
    assert common.identity_from_cas('achen', '500111111') == ('500111111', 'student')
    assert common.identity_from_cas('nobody') == (None, None)              # unrecognized
    assert common.identity_from_cas(None) == (None, None)                  # no header


def test_a_students_username_alone_does_not_resolve_them(db):
    """The bug this replaced: assuming CAS could put the number into Cas-User.

    mod_auth_cas keeps Cas-User as the username, so a student arriving with only that
    must not resolve, or every student would be an unknown user in production and we
    would find out on the first day of class.
    """
    import common
    assert common.identity_from_cas('achen') == (None, None)


def test_an_account_that_is_both_is_treated_as_staff(db):
    """An instructor who also has a student number gets the marking screens."""
    import common
    assert common.identity_from_cas('dmason', '500111111') == ('dmason', 'staff')


def test_production_reads_staff_identity_from_cas_header(db, monkeypatch):
    """In production the Cas-User header (set by Apache) is the identity, not a session."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    resp = app_module.app.test_client().post(
        '/save/500111111/1/achieved', headers={'Cas-User': 'dmason'})
    assert resp.status_code == 200
    assert achievement_count() == 1


def test_production_reads_a_student_from_the_attribute_header(db, monkeypatch):
    """End to end: a student signs in with their username, and the app knows their
    number because CAS sent it as its own header."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    resp = app_module.app.test_client().get(
        '/view/500111111',
        headers={'Cas-User': 'achen', 'CAS-studentnumber': '500111111'})
    assert resp.status_code == 200
    assert 'Progress' in resp.get_data(as_text=True)


def test_the_attribute_header_name_can_be_changed_without_a_deploy(db, monkeypatch):
    """The prefix is CCS's config, not ours, so it comes from settings."""
    import app as app_module
    import db as db_module
    with db_module.cursor() as sql:
        sql.execute("insert or replace into settings (key, value) "
                    "values ('cas_student_number_header', 'X-Number')")
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    resp = app_module.app.test_client().get(
        '/view/500111111',
        headers={'Cas-User': 'achen', 'X-Number': '500111111'})
    assert resp.status_code == 200


def test_production_without_a_cas_header_is_anonymous(db, monkeypatch):
    """No header means unauthenticated: they must not be able to act."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    resp = app_module.app.test_client().post('/save/500111111/1/achieved')
    assert resp.status_code == 403
    assert achievement_count() == 0
