"""Demonstrating a harder competency credits the ones it proves (#80).

Dave asked for this on Aug 26 for one reason: time. Roughly 100 evaluations a session
at about 7 minutes each leaves no room to test something a student has already shown.
If they can do nested ifs they can do simple ifs, and spending a slot proving it again
is a slot nobody has.

The three rules these tests pin down, all decided before any of it was built:

1. one sitting of work means one row in `evaluations`, on the competency actually
   demonstrated. A credit is a pass with no evaluation behind it.
2. an undo takes back the credits that tap created, because a mis-tap otherwise leaves
   a student passed on competencies nobody tested, invisibly.
3. covering follows the chain. If nested proves simple and simple proves comparison,
   nested proves comparison.
"""
import sqlite3

import pytest

import db as db_module
import logic


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Three competencies in a chain: 1 covers 2, 2 covers 3. 4 is unrelated."""
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
        for cid, name in [(1, 'Nested ifs'), (2, 'Simple ifs'),
                          (3, 'Comparison operators'), (4, 'File writing')]:
            sql.execute("insert into competencies (id, name) values (?, ?)", (cid, name))
        sql.execute("insert into competency_covers values (1, 2)")
        sql.execute("insert into competency_covers values (2, 3)")
    return db_module


def state(sql, competency_id, student='500111111'):
    row = sql.execute(
        "select status from achievements "
        " where student_number = ? and competency_id = ?",
        (student, competency_id)).fetchone()
    return row[0] if row else None


def evaluation_count(sql, competency_id=None, student='500111111'):
    if competency_id is None:
        return sql.execute(
            "select count(*) from evaluations where student_number = ?",
            (student,)).fetchone()[0]
    return sql.execute(
        "select count(*) from evaluations "
        " where student_number = ? and competency_id = ?",
        (student, competency_id)).fetchone()[0]


# --- the rule, in the abstract ---------------------------------------------

def test_covering_follows_the_chain():
    edges = {1: {2}, 2: {3}}
    assert logic.covered_by(1, edges) == {2, 3}


def test_a_cycle_terminates_instead_of_hanging_the_marking_screen():
    """Somebody will write X covers Y and Y covers X halfway through a list of eighty.

    That is wrong, but it must not be an infinite loop in the middle of a session.
    """
    assert logic.covered_by(1, {1: {2}, 2: {1}}) == {2}
    assert logic.covered_by(1, {1: {1}}) == set()


def test_two_paths_to_the_same_competency_is_not_a_problem():
    assert logic.covered_by(1, {1: {2, 3}, 2: {4}, 3: {4}}) == {2, 3, 4}


# --- crediting -------------------------------------------------------------

def test_a_pass_credits_what_it_proves(db):
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        assert state(sql, 1) == 'achieved'
        assert state(sql, 2) == 'achieved'   # nested proves simple
        assert state(sql, 3) == 'achieved'   # and simple proves comparison
        assert state(sql, 4) is None         # unrelated, untouched


def test_a_credit_is_not_an_evaluation(db):
    """One sitting of work, one row in the logbook, on what was actually demonstrated.

    A row per credited competency would tell the evaluator report this TA did three
    evaluations when they did one, which is the report's whole purpose defeated.
    """
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        assert evaluation_count(sql) == 1
        assert evaluation_count(sql, 1) == 1
        assert evaluation_count(sql, 2) == 0


def test_failing_credits_nothing(db):
    # Not passing nested ifs says nothing either way about simple ifs.
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 1, 'cooling_off', 'dmason')
        assert state(sql, 2) is None


def test_a_credit_never_overwrites_a_result_a_ta_gave(db):
    """A TA marked simple ifs 'not passed'. A credit must not quietly flip it."""
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 2, 'cooling_off', 'lfortune')
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        assert state(sql, 2) == 'cooling_off'
        assert state(sql, 3) == 'achieved'   # untouched ones still get credited


def test_no_coverage_recorded_means_nothing_changes(db):
    """The map is empty until #2 settles the list, so this is the shipping behaviour."""
    with db.cursor() as sql:
        sql.execute("delete from competency_covers")
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        assert state(sql, 1) == 'achieved'
        assert state(sql, 2) is None


# --- undo ------------------------------------------------------------------

def test_undo_takes_back_the_credits_that_tap_created(db):
    """The mis-tap this exists for: one wrong tap, five passes, one undo."""
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        db.clear_achievement(sql, '500111111', 1)
        assert state(sql, 1) is None
        assert state(sql, 2) is None
        assert state(sql, 3) is None


def test_undo_leaves_alone_what_the_student_earned(db):
    """Alice passed simple ifs herself on Tuesday. Undoing nested ifs is not about her."""
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 2, 'achieved', 'lfortune')
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        db.clear_achievement(sql, '500111111', 1)
        assert state(sql, 1) is None
        assert state(sql, 2) == 'achieved'   # earned, has an evaluation behind it
        # 3 was credited by 2, which Alice still holds, so it survives too.
        assert state(sql, 3) == 'achieved'


def test_a_credit_survives_if_something_else_still_proves_it(db):
    """Two competencies both cover simple ifs. Undoing one leaves the other proving it."""
    with db.cursor() as sql:
        sql.execute("insert into competency_covers values (4, 2)")
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        db.record_achievement(sql, '500111111', 4, 'achieved', 'dmason')
        db.clear_achievement(sql, '500111111', 1)
        assert state(sql, 2) == 'achieved'   # 4 still covers it
        assert state(sql, 3) == 'achieved'   # and 2 still covers 3


def test_undo_does_not_touch_an_unrelated_competency(db):
    with db.cursor() as sql:
        db.record_achievement(sql, '500111111', 4, 'achieved', 'dmason')
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        db.clear_achievement(sql, '500111111', 1)
        assert state(sql, 4) == 'achieved'


def test_one_students_credits_are_not_another_students(db):
    with db.cursor() as sql:
        sql.execute("insert into students values ('Ben', 'Okafor', '500222222')")
        db.record_achievement(sql, '500222222', 1, 'achieved', 'dmason')
        db.record_achievement(sql, '500111111', 1, 'achieved', 'dmason')
        db.clear_achievement(sql, '500111111', 1)
        assert state(sql, 2, '500222222') == 'achieved'
        assert state(sql, 2, '500111111') is None


# --- through the actual screen ---------------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_marking_from_the_mark_screen_credits_too(db):
    """A regression test, because every test above passed while this did nothing.

    `/save/<competency_id>` is an untyped route, so it hands the write path the string
    '1' where the queue screen hands it the integer 1. SQLite treats those the same, so
    the achievement row landed and the screen looked correct; the dict lookup that finds
    coverage did not, so one of the two marking screens credited nothing at all. Calling
    record_achievement directly, the way the tests above do, never sees it.
    """
    client = signed_in_as('dmason', 'staff')
    assert client.post('/save/500111111/1/achieved').status_code == 200
    with db.cursor() as sql:
        assert state(sql, 2) == 'achieved'
        assert state(sql, 3) == 'achieved'


def test_undo_from_the_mark_screen_takes_the_credits_back_too(db):
    client = signed_in_as('dmason', 'staff')
    client.post('/save/500111111/1/achieved')
    assert client.post('/save/500111111/1/unassessed').status_code == 200
    with db.cursor() as sql:
        assert state(sql, 1) is None
        assert state(sql, 2) is None
        assert state(sql, 3) is None
