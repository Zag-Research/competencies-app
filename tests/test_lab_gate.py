"""Seat entry is restricted to studio lab machines (#46).

Dave's scope on that issue: "anybody can open it anywhere and has CAS authentication
... Seat number only is an option for a student logged into a lab machine in the lab."
So exactly one action is gated, and everything else stays reachable from anywhere.

The detection method came from CS systems: reverse-resolve the caller's address and
match the name against the lab pattern (eng201-01 and friends). Development is always
treated as in-lab, so these tests force production mode to exercise the gate at all.
"""
import sqlite3
from datetime import date

import pytest

import common
import db as db_module
import logic

TUE = '2026-07-28'   # a real studio day


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
        sql.execute("insert into competencies (id, name) values (1, 'Nested loops')")
    return db_module


@pytest.fixture
def in_production(monkeypatch):
    """Run the app as it runs on the server: CAS identity, and the lab gate live."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'ENV', 'production')
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    common._HOSTNAME_CACHE.clear()
    return app_module.app


def resolves_to(monkeypatch, hostname):
    """Make reverse DNS return `hostname`, or fail if it is None."""
    common._HOSTNAME_CACHE.clear()

    def fake(address):
        if hostname is None:
            raise OSError('no reverse entry')
        return (hostname, [], [address])

    monkeypatch.setattr(common.socket, 'gethostbyaddr', fake)


# In production a student arrives as two headers: their TMU username in Cas-User, and
# their student number as a CAS attribute. The number is what identifies them here.
def student_headers(student='500111111', username='achen'):
    return {'Cas-User': username, 'CAS-studentnumber': student}


def seat_post(app, seat='12', student='500111111'):
    return app.test_client().post('/queue/seat', data={'seat': seat},
                                  headers=student_headers(student))


def attendance_count(student='500111111'):
    with db_module.cursor() as sql:
        return sql.execute(
            'select count(*) from attendance where student_number = ?', (student,)
        ).fetchone()[0]


# --- the rule on its own -------------------------------------------------

def test_lab_machine_names_match():
    assert logic.is_lab_host('eng201-01') is True
    assert logic.is_lab_host('eng201-01.cs.torontomu.ca') is True
    assert logic.is_lab_host('ENG305-12') is True          # case does not matter


def test_other_names_do_not_match():
    assert logic.is_lab_host('sarahs-macbook') is False
    assert logic.is_lab_host('') is False
    assert logic.is_lab_host(None) is False


def test_a_name_that_merely_contains_the_pattern_does_not_match():
    """Matching a substring would let someone name a home machine to slip through."""
    assert logic.is_lab_host('noteng201-01') is False
    assert logic.is_lab_host('eng201-01-vpn') is False


def test_the_pattern_can_be_overridden_from_settings():
    """The room or its naming can change without a deploy."""
    assert logic.is_lab_host('lab7-3', pattern=r'lab\d+-\d+') is True
    assert logic.is_lab_host('eng201-01', pattern=r'lab\d+-\d+') is False


# --- the gate, in production --------------------------------------------

def test_a_seat_from_a_lab_machine_is_accepted(db, in_production, monkeypatch):
    resolves_to(monkeypatch, 'eng201-04.cs.torontomu.ca')
    seat_post(in_production)
    assert attendance_count() == 1


def test_a_seat_from_a_laptop_at_home_is_rejected(db, in_production, monkeypatch):
    resolves_to(monkeypatch, 'cpe-24-90-11-3.nyc.res.rr.com')
    seat_post(in_production)
    assert attendance_count() == 0


def test_an_unresolvable_address_is_rejected(db, in_production, monkeypatch):
    """A home address usually has no reverse entry, which is indistinguishable from
    DNS being down, so the safe reading of "cannot resolve" is "not the lab"."""
    resolves_to(monkeypatch, None)
    seat_post(in_production)
    assert attendance_count() == 0


def test_a_dns_failure_is_not_cached(db, in_production, monkeypatch):
    """A transient failure must not lock an address out for the life of the process."""
    resolves_to(monkeypatch, None)
    seat_post(in_production)
    assert attendance_count() == 0
    resolves_to(monkeypatch, 'eng201-04')        # DNS comes back
    seat_post(in_production)
    assert attendance_count() == 1


def test_the_seat_form_is_hidden_outside_the_lab(db, in_production, monkeypatch):
    resolves_to(monkeypatch, 'sarahs-macbook')
    body = in_production.test_client().get(
        '/queue', headers=student_headers()).get_data(as_text=True)
    assert 'queue-seat-entry' not in body
    assert 'can only be entered from a lab machine' in body


def test_the_rest_of_the_page_still_works_outside_the_lab(db, in_production, monkeypatch):
    """Dave: anybody can open it anywhere. Only the seat is gated."""
    resolves_to(monkeypatch, 'sarahs-macbook')
    body = in_production.test_client().get(
        '/queue', headers=student_headers()).get_data(as_text=True)
    assert 'Nested loops' in body          # can still see and sign up for competencies


def test_development_is_always_treated_as_in_the_lab(db, monkeypatch):
    """Requiring a lab machine to work on the app locally would be absurd."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    client.post('/queue/seat', data={'seat': '12'})
    assert attendance_count() == 1


# --- the escape hatch: a TA sets a seat for a student ----------------------

@pytest.fixture
def booked(db, monkeypatch):
    """A student booked for today's session, with no seat, so invisible to staff."""
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 28))
    with db_module.cursor() as sql:
        sql.execute(
            """insert into requests
                   (student_number, competency_id, requested_at, status, studio_date)
               values ('500111111', 1, CURRENT_TIMESTAMP, 'waiting', ?)""",
            (TUE,))
    return db


def staff_client():
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = 'dmason'
        s['role'] = 'staff'
    return client


def seat_of(student='500111111'):
    with db_module.cursor() as sql:
        return sql.execute(
            'select seat from requests where student_number = ?', (student,)
        ).fetchone()[0]


def test_a_seatless_student_is_listed_for_staff(booked):
    """They are not claimable, but staff must be able to see and reach them."""
    body = staff_client().get('/queue').get_data(as_text=True)
    assert 'Signed up, no seat yet' in body
    assert 'Chen, Alice' in body


def test_a_ta_can_set_a_students_seat(booked):
    staff_client().post('/queue/seat-for/500111111', data={'seat': '14'})
    assert seat_of() == '14'
    assert attendance_count() == 1


def test_the_override_is_not_itself_lab_gated(booked, in_production, monkeypatch):
    """Gating the escape hatch on the thing that just failed would make it useless.

    A TA is on an iPad on wifi, which never resolves to a lab machine, and the whole
    point is to rescue a session when the student's own gate misfires.
    """
    resolves_to(monkeypatch, 'some-ipad-on-wifi')
    import app as app_module
    app_module.app.test_client().post(
        '/queue/seat-for/500111111', data={'seat': '14'},
        headers={'Cas-User': 'dmason'})
    assert seat_of() == '14'


def test_a_student_cannot_seat_themselves_through_the_override(booked):
    """Otherwise it is just the lab gate with an extra step."""
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = '500111111'
        s['role'] = 'student'
    client.post('/queue/seat-for/500111111', data={'seat': '14'})
    assert seat_of() is None
    assert attendance_count() == 0


def test_the_override_needs_an_actual_seat(booked):
    staff_client().post('/queue/seat-for/500111111', data={'seat': '  '})
    assert seat_of() is None


def test_the_override_does_nothing_off_a_studio_day(db, monkeypatch):
    monkeypatch.setattr(logic, 'today_toronto', lambda: date(2026, 7, 25))  # Saturday
    staff_client().post('/queue/seat-for/500111111', data={'seat': '14'})
    assert attendance_count() == 0


# --- the refusal has to say what it saw (#100) ------------------------------

def student_page(app, student='500111111'):
    return app.test_client().get('/queue', headers=student_headers(student)
                                 ).get_data(as_text=True)


def test_a_refusal_names_the_machine_it_resolved(db, in_production, monkeypatch):
    """The pattern has never been tested against a real studio machine.

    If it is even slightly wrong, every student in the room is refused, and a message
    that only says "use a lab machine" tells nobody why. Naming the resolved hostname
    puts the answer on the first blocked student's screen: somebody reads the real name
    off it and puts it in lab_host_pattern, which is a row update, no redeploy.
    """
    resolves_to(monkeypatch, 'eng-201-05.ecb.torontomu.ca')     # a plausible near miss
    body = student_page(in_production)
    assert 'eng-201-05.ecb.torontomu.ca' in body
    assert 'show this to a TA' in body


def test_it_says_so_when_nothing_resolved(db, in_production, monkeypatch):
    """No reverse entry is both a student at home and a DNS server that did not answer,
    and the difference matters to whoever is debugging it."""
    resolves_to(monkeypatch, None)
    body = student_page(in_production)
    assert 'no name we could look up' in body


def test_a_student_in_the_lab_is_not_shown_any_of_this(db, in_production, monkeypatch):
    resolves_to(monkeypatch, 'eng201-04.cs.torontomu.ca')
    body = student_page(in_production)
    assert 'show this to a TA' not in body
    assert 'Where are you sitting?' in body


def test_the_posted_refusal_names_it_too(db, in_production, monkeypatch):
    """A student who submits anyway, or whose page was stale, gets the same answer."""
    resolves_to(monkeypatch, 'eng-201-05.ecb.torontomu.ca')
    client = in_production.test_client()
    client.post('/queue/seat', data={'seat': '12'}, headers=student_headers())
    body = client.get('/queue', headers=student_headers()).get_data(as_text=True)
    assert 'eng-201-05.ecb.torontomu.ca' in body


def test_relaxing_the_pattern_lets_everybody_in(db, in_production, monkeypatch):
    """The escape hatch, and the reason this is survivable on the first morning.

    If the pattern turns out to be wrong, one row update opens the gate and attendance
    keeps working while it is fixed properly.
    """
    resolves_to(monkeypatch, 'anything-at-all.example.com')
    with db_module.cursor() as sql:
        sql.execute("update settings set value = '.*' where key = 'lab_host_pattern'")
    assert 'Where are you sitting?' in student_page(in_production)
