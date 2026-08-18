"""Worth reading (#51): curated links, and whether students actually open them.

Shape settled by Dave on the issue: "I'd show maybe the last 3, but make it scrollable
so they can see older ones. Yes, track click-throughs, probably per student so we can
encourage students to stay engaged. For now, instructor curating."
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
        sql.execute("insert into competencies (id, name) values (1, 'Nested loops')")
    return db_module


def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def add(title='Why review matters', why='Five minutes.', url='https://example.com/a'):
    with db_module.cursor() as sql:
        db_module.add_link(sql, title, why, url)
        return sql.lastrowid


# --- curation is instructor-only ------------------------------------------

def test_staff_can_add_and_remove_a_link(db):
    staff = signed_in_as('dmason', 'staff')
    staff.post('/links/add', data={'title': 'A post', 'why': 'Short.',
                                   'url': 'https://example.com/x'})
    with db.cursor() as sql:
        rows = db.links_newest_first(sql)
    assert [r[1] for r in rows] == ['A post']
    staff.post('/links/%d/delete' % rows[0][0])
    with db.cursor() as sql:
        assert db.links_newest_first(sql) == []


def test_students_cannot_curate(db):
    student = signed_in_as('500111111', 'student')
    student.post('/links/add', data={'title': 'Mine', 'url': 'https://example.com/m'})
    assert signed_in_as('500111111', 'student').get('/links').status_code == 302
    with db.cursor() as sql:
        assert db.links_newest_first(sql) == []


def test_a_link_needs_a_title_and_an_http_url(db):
    staff = signed_in_as('dmason', 'staff')
    staff.post('/links/add', data={'title': '', 'url': 'https://example.com/x'})
    staff.post('/links/add', data={'title': 'No scheme', 'url': 'example.com'})
    staff.post('/links/add', data={'title': 'Nope', 'url': 'javascript:alert(1)'})
    with db.cursor() as sql:
        assert db.links_newest_first(sql) == []


def test_newest_first(db):
    with db.cursor() as sql:
        db.add_link(sql, 'First', '', 'https://example.com/1')
        db.add_link(sql, 'Second', '', 'https://example.com/2')
        assert [r[1] for r in db.links_newest_first(sql)] == ['Second', 'First']


# --- opening a link -------------------------------------------------------

def test_opening_a_link_redirects_to_it_and_records_the_click(db):
    lid = add()
    response = signed_in_as('500111111', 'student').get('/link/%d' % lid)
    assert response.status_code == 302
    assert response.headers['Location'] == 'https://example.com/a'
    with db.cursor() as sql:
        assert db.link_engagement(sql) == {lid: 1}


def test_opening_the_same_link_twice_still_counts_as_one_student(db):
    """This records WHETHER a student read something, not how keen they were."""
    lid = add()
    student = signed_in_as('500111111', 'student')
    student.get('/link/%d' % lid)
    student.get('/link/%d' % lid)
    with db.cursor() as sql:
        assert db.link_engagement(sql) == {lid: 1}


def test_staff_previewing_a_link_does_not_count(db):
    """Staff clicks would dilute the number the page exists to produce."""
    lid = add()
    response = signed_in_as('dmason', 'staff').get('/link/%d' % lid)
    assert response.headers['Location'] == 'https://example.com/a'
    with db.cursor() as sql:
        assert db.link_engagement(sql) == {}


def test_a_link_that_no_longer_exists_does_not_error(db):
    response = signed_in_as('500111111', 'student').get('/link/999')
    assert response.status_code == 302
    assert 'example.com' not in response.headers['Location']


def test_removing_a_link_takes_its_clicks_with_it(db):
    lid = add()
    signed_in_as('500111111', 'student').get('/link/%d' % lid)
    with db.cursor() as sql:
        db.remove_link(sql, lid)
        assert db.link_engagement(sql) == {}


# --- who to encourage -----------------------------------------------------

def test_students_who_have_opened_nothing_are_listed(db):
    lid = add()
    signed_in_as('500111111', 'student').get('/link/%d' % lid)
    with db.cursor() as sql:
        names = [n for (_f, _l, n) in db.students_with_no_clicks(sql)]
    assert names == ['500222222']      # Alice read it, Ben did not


# --- the student's page ---------------------------------------------------

def test_the_reading_list_shows_on_a_students_own_page(db):
    add(title='Why review matters')
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'Worth reading' in body
    assert 'Why review matters' in body
    # Linked through the tracking hop, not straight out to the article.
    assert 'href="/link/' in body


def test_every_link_is_rendered_so_older_ones_stay_reachable(db):
    """Dave asked for 3 visible and the rest scrollable, which is a height on the
    container, not a limit on the query. All five must be in the markup."""
    for i in range(5):
        add(title='Piece %d' % i, url='https://example.com/%d' % i)
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    for i in range(5):
        assert 'Piece %d' % i in body


def test_nothing_is_shown_when_the_list_is_empty(db):
    body = signed_in_as('500111111', 'student').get(
        '/view/500111111').get_data(as_text=True)
    assert 'Worth reading' not in body
