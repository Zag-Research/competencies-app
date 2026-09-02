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


# --- production: CAS knows you, the app does not (#90) ----------------------

def production(monkeypatch):
    """The app as it runs behind Apache: identity comes from headers, not the form."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    return app_module.app.test_client()


def test_an_unrecognised_person_is_told_what_cas_actually_sent(db, monkeypatch):
    """The whole point: nobody can verify in advance what TMU puts in Cas-User.

    Whoever hits this first reads their own identifier off the screen, and that exact
    string goes into the admins setting. No guessing, and no redeploy.
    """
    body = production(monkeypatch).get(
        '/login', headers={'Cas-User': 'whatever.cas.sends'}).get_data(as_text=True)
    assert 'whatever.cas.sends' in body
    assert 'not on a list' in body


def test_it_says_whether_the_student_number_attribute_arrived(db, monkeypatch):
    """Staff never need the attribute, so a staff-only check would pass while every
    student login was broken. This is where that becomes visible."""
    client = production(monkeypatch)
    missing = client.get('/login', headers={'Cas-User': 'someone'}).get_data(as_text=True)
    assert 'not sent' in missing
    assert 'not releasing attributes' in missing

    arrived = client.get('/login', headers={'Cas-User': 'someone',
                                            'CAS-studentnumber': '500111111'}
                         ).get_data(as_text=True)
    assert '500111111' in arrived
    assert 'not releasing attributes' not in arrived


def test_the_dev_login_form_is_not_reachable_in_production(db, monkeypatch):
    """It sets a session production ignores, so it is a dead end that looks like a fix."""
    body = production(monkeypatch).get(
        '/login', headers={'Cas-User': 'someone'}).get_data(as_text=True)
    assert 'Sign in' not in body
    assert 'name="username"' not in body


def test_development_still_gets_the_login_form(db):
    import app as app_module
    body = app_module.app.test_client().get('/login').get_data(as_text=True)
    assert 'name="username"' in body


def test_every_page_carries_the_mobile_viewport(db):
    """Dave asked for this to work on a phone (#96).

    Without the tag, a phone lays the page out at a virtual 980px and scales the result
    down, so the CSS never applies at the real screen width. Text comes out unreadably
    small, and zooming in means scrolling sideways to reach the achieved badges at the
    right of every row. It reads as content being cut off.
    """
    body = client_as('dmason', 'staff').get('/queue').get_data(as_text=True)
    assert 'name="viewport"' in body
    assert 'width=device-width' in body


def test_the_tab_says_what_the_app_is(db):
    """It said "Computer Science Admin", inherited from the template myhtml came from."""
    body = client_as('dmason', 'staff').get('/queue').get_data(as_text=True)
    assert '<title>Competency Tracker</title>' in body


def test_the_stylesheet_has_no_unclosed_rules(db):
    """An unclosed rule makes the CSS parser swallow everything after it, silently.

    `.awaiting-row input` was missing its brace, so eight rules below it never applied:
    the whole reading list, add-a-student, and the coverage hint. Nothing errors, no
    page looks broken enough to notice, and the styles are simply absent.
    """
    import re
    css = open('static/css/main.css').read()
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    assert css.count('{') == css.count('}'), (
        'unbalanced braces in main.css: %d open, %d close. Everything after the '
        'unclosed rule is being ignored by the browser.'
        % (css.count('{'), css.count('}')))
