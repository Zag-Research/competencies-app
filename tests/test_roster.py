"""Loading and maintaining the real roster (#61).

Students can add a course until mid-September and drop until late November, so this is
never a one-time load. The rule that shapes everything here: it never deletes. A drop is
marked, because the student's results have to survive it and a drop can be reversed.
"""
import os
import sqlite3
from datetime import date

import pytest

import db as db_module
import import_roster


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'course-data.db'
    with open('schema.sql') as f:
        schema = f.read()
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.commit()
    connection.close()
    monkeypatch.setattr(db_module, 'DB_PATH', str(path))
    with db_module.cursor() as sql:
        sql.execute("insert into competencies (id, name, course) values (1, 'Loops', 'CPS109')")
        sql.execute("insert into competencies (id, name, course) values (2, 'Latches', 'CPS213')")
    return str(path)


def write_csv(tmp_path, rows, header='student_number,first_name,last_name,course'):
    path = tmp_path / 'roster.csv'
    path.write_text(header + '\n' + '\n'.join(rows) + '\n')
    return str(path)


def run(db_path, csv_path, today=None):
    connection = sqlite3.connect(db_path)
    try:
        rows = import_roster.read_rows(csv_path)
        import_roster.apply(connection, rows, today=today)
    finally:
        connection.close()


def enrollment(db_path, number, course):
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            'select withdrawn_on from enrollments where student_number = ? and course = ?',
            (number, course)).fetchone()
    finally:
        connection.close()
    return row


# --- reading the file -----------------------------------------------------

def test_a_missing_column_is_reported_not_guessed(db, tmp_path):
    path = write_csv(tmp_path, ['500111111,Alice,Chen'],
                     header='student_number,first_name,last_name')
    with pytest.raises(ValueError) as problem:
        import_roster.read_rows(path)
    assert 'course' in str(problem.value)


def test_column_names_are_matched_loosely(db, tmp_path):
    """Exports vary. "Student Number" and student_number are the same thing."""
    path = write_csv(tmp_path, ['500111111,Alice,Chen,CPS109'],
                     header='Student Number,First Name,Last Name,Course')
    assert import_roster.read_rows(path)[0]['student_number'] == '500111111'


def test_a_row_missing_a_value_is_refused(db, tmp_path):
    """Half a student is worse than no student: they could never sign in."""
    path = write_csv(tmp_path, ['500111111,Alice,,CPS109'])
    with pytest.raises(ValueError) as problem:
        import_roster.read_rows(path)
    assert 'line 2' in str(problem.value)


# --- importing ------------------------------------------------------------

def test_students_and_enrollments_are_loaded(db, tmp_path):
    path = write_csv(tmp_path, ['500111111,Alice,Chen,CPS109',
                                '500111111,Alice,Chen,CPS213'])
    run(db, path)
    with db_module.cursor() as sql:
        assert db_module.enrolled_courses(sql, '500111111') == ['CPS109', 'CPS213']


def test_running_twice_changes_nothing(db, tmp_path):
    path = write_csv(tmp_path, ['500111111,Alice,Chen,CPS109'])
    run(db, path)
    run(db, path)
    connection = sqlite3.connect(db)
    try:
        assert connection.execute('select count(*) from students').fetchone()[0] == 1
        assert connection.execute('select count(*) from enrollments').fetchone()[0] == 1
    finally:
        connection.close()


def test_a_corrected_name_is_updated(db, tmp_path):
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109']))
    path = tmp_path / 'fixed.csv'
    path.write_text('student_number,first_name,last_name,course\n'
                    '500111111,Alice,Chen-Wong,CPS109\n')
    run(db, str(path))
    connection = sqlite3.connect(db)
    try:
        assert connection.execute(
            'select last_name from students').fetchone()[0] == 'Chen-Wong'
    finally:
        connection.close()


# --- drops: the rule that matters -----------------------------------------

def test_a_student_missing_from_a_later_file_is_marked_not_deleted(db, tmp_path):
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109']))
    with db_module.cursor() as sql:
        sql.execute("insert into achievements (student_number, competency_id, status,"
                    " date_recorded) values ('500111111', 1, 'achieved', '2026-09-15 10:00')")
    dropped = tmp_path / 'after.csv'
    dropped.write_text('student_number,first_name,last_name,course\n'
                       '500222222,Ben,Okafor,CPS109\n')
    run(db, str(dropped), today=date(2026, 10, 3))

    connection = sqlite3.connect(db)
    try:
        # The student is still there, and so is everything they earned.
        assert connection.execute(
            "select count(*) from students where student_number = '500111111'"
        ).fetchone()[0] == 1
        assert connection.execute('select count(*) from achievements').fetchone()[0] == 1
    finally:
        connection.close()
    assert enrollment(db, '500111111', 'CPS109') == ('2026-10-03',)


def test_a_dropped_student_sees_no_competencies_not_all_of_them(db, tmp_path):
    """The trap: competencies_for reads "no rows" as "taking everything", so deleting a
    dropped student's enrollment would have shown them the full list of both courses."""
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109']))
    empty = tmp_path / 'after.csv'
    empty.write_text('student_number,first_name,last_name,course\n'
                     '500222222,Ben,Okafor,CPS109\n')
    run(db, str(empty))
    with db_module.cursor() as sql:
        assert db_module.competencies_for(sql, '500111111') == []


def test_a_student_we_have_no_record_for_still_sees_everything(db):
    """The safe default for a roster that has not been loaded yet (#11) must survive."""
    with db_module.cursor() as sql:
        sql.execute("insert into students values ('Dana', 'Ng', '500444444')")
        assert len(db_module.competencies_for(sql, '500444444')) == 2


def test_a_reversed_drop_restores_them(db, tmp_path):
    first = write_csv(tmp_path, ['500111111,Alice,Chen,CPS109'])
    run(db, first)
    gone = tmp_path / 'gone.csv'
    gone.write_text('student_number,first_name,last_name,course\n'
                    '500222222,Ben,Okafor,CPS109\n')
    run(db, str(gone))
    run(db, first)                                   # they re-enrolled
    assert enrollment(db, '500111111', 'CPS109') == (None,)
    with db_module.cursor() as sql:
        assert db_module.enrolled_courses(sql, '500111111') == ['CPS109']


# --- the dry run ----------------------------------------------------------

def test_the_plan_reports_without_changing_anything(db, tmp_path):
    path = write_csv(tmp_path, ['500111111,Alice,Chen,CPS109'])
    connection = sqlite3.connect(db)
    try:
        added, _updated, enrolled, _returning, _withdrawn = import_roster.plan(
            connection, import_roster.read_rows(path))
        assert len(added) == 1 and len(enrolled) == 1
        assert connection.execute('select count(*) from students').fetchone()[0] == 0
    finally:
        connection.close()


# --- the staff page -------------------------------------------------------

def signed_in_as(username, role):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'] = username
        s['role'] = role
    return client


def test_a_ta_can_add_a_student_who_is_not_on_the_roster(db):
    signed_in_as('dmason', 'staff').post('/students/add', data={
        'student_number': '500999999', 'first_name': 'New', 'last_name': 'Student',
        'courses': ['CPS109']})
    with db_module.cursor() as sql:
        assert db_module.lookup_role('500999999') == 'student'
        assert db_module.enrolled_courses(sql, '500999999') == ['CPS109']


def test_adding_someone_who_already_exists_corrects_them(db, tmp_path):
    """A TA does not know whether the student is already there, and should not have to."""
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109']))
    signed_in_as('dmason', 'staff').post('/students/add', data={
        'student_number': '500111111', 'first_name': 'Alice', 'last_name': 'Chen-Wong',
        'courses': ['CPS109', 'CPS213']})
    with db_module.cursor() as sql:
        assert db_module.enrolled_courses(sql, '500111111') == ['CPS109', 'CPS213']


def test_adding_a_dropped_student_back_clears_the_withdrawal(db, tmp_path):
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109']))
    empty = tmp_path / 'after.csv'
    empty.write_text('student_number,first_name,last_name,course\n'
                     '500222222,Ben,Okafor,CPS109\n')
    run(db, str(empty))
    signed_in_as('dmason', 'staff').post('/students/add', data={
        'student_number': '500111111', 'first_name': 'Alice', 'last_name': 'Chen',
        'courses': ['CPS109']})
    assert enrollment(db, '500111111', 'CPS109') == (None,)


def test_an_incomplete_add_is_refused(db):
    signed_in_as('dmason', 'staff').post('/students/add', data={
        'student_number': '500999999', 'first_name': 'New', 'last_name': '',
        'courses': ['CPS109']})
    assert db_module.lookup_role('500999999') is None


def test_students_cannot_add_students(db):
    signed_in_as('500111111', 'student').post('/students/add', data={
        'student_number': '500999999', 'first_name': 'New', 'last_name': 'Student',
        'courses': ['CPS109']})
    assert db_module.lookup_role('500999999') is None


# --- single-course exports, which is what D2L actually gives you ----------

def test_a_file_with_no_course_column_works_if_the_course_is_given(db, tmp_path):
    """A D2L export happens from inside one course, so the course is never in the file."""
    path = tmp_path / 'cps109.csv'
    path.write_text('student_number,first_name,last_name\n500111111,Alice,Chen\n')
    rows = import_roster.read_rows(str(path), course='CPS109')
    assert rows[0]['course'] == 'CPS109'


def test_without_a_course_the_column_is_still_required(db, tmp_path):
    path = tmp_path / 'cps109.csv'
    path.write_text('student_number,first_name,last_name\n500111111,Alice,Chen\n')
    with pytest.raises(ValueError) as problem:
        import_roster.read_rows(str(path))
    assert 'course' in str(problem.value)


def test_importing_one_course_does_not_drop_the_other(db, tmp_path):
    """The trap in per-course imports.

    Alice takes both. Importing only the CPS109 list must not read her absence from
    that file as having dropped CPS213, or the first import of the term would wipe
    every student's second course.
    """
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109',
                                 '500111111,Alice,Chen,CPS213']))
    only109 = tmp_path / 'cps109.csv'
    only109.write_text('student_number,first_name,last_name\n500111111,Alice,Chen\n')

    connection = sqlite3.connect(db)
    try:
        rows = import_roster.read_rows(str(only109), course='CPS109')
        import_roster.apply(connection, rows, today=date(2026, 10, 3), course='CPS109')
    finally:
        connection.close()

    assert enrollment(db, '500111111', 'CPS109') == (None,)
    assert enrollment(db, '500111111', 'CPS213') == (None,)   # untouched


def test_a_per_course_import_still_marks_drops_within_that_course(db, tmp_path):
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109',
                                 '500222222,Ben,Okafor,CPS109']))
    only_ben = tmp_path / 'cps109.csv'
    only_ben.write_text('student_number,first_name,last_name\n500222222,Ben,Okafor\n')

    connection = sqlite3.connect(db)
    try:
        rows = import_roster.read_rows(str(only_ben), course='CPS109')
        import_roster.apply(connection, rows, today=date(2026, 10, 3), course='CPS109')
    finally:
        connection.close()

    assert enrollment(db, '500111111', 'CPS109') == ('2026-10-03',)
    assert enrollment(db, '500222222', 'CPS109') == (None,)


def test_students_in_only_one_course_are_reported(db, tmp_path):
    """Importing one list and forgetting the other is otherwise silent.

    Dave's rule is that everyone takes both, so a student with one enrollment almost
    always means only one course's file has been loaded. Those students would never see
    the other course's competencies and could not sign up for them, and nothing in the
    app would say so.
    """
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109',
                                 '500111111,Alice,Chen,CPS213',
                                 '500222222,Ben,Okafor,CPS109']))
    connection = sqlite3.connect(db)
    try:
        alone = import_roster.single_course_students(connection)
    finally:
        connection.close()
    assert [(n, c) for (n, _name, c) in alone] == [('500222222', 'CPS109')]


def test_nobody_is_reported_when_everyone_takes_both(db, tmp_path):
    run(db, write_csv(tmp_path, ['500111111,Alice,Chen,CPS109',
                                 '500111111,Alice,Chen,CPS213']))
    connection = sqlite3.connect(db)
    try:
        assert import_roster.single_course_students(connection) == []
    finally:
        connection.close()


def test_the_course_tickboxes_stay_together(db):
    """Loose in the form they wrapped as separate items, so CPS109 sat beside the name
    fields and CPS213 was orphaned next to the button (#118). Grouped, the row breaks
    between groups instead of through the middle of one."""
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s['user'], s['role'] = 'dmason', 'staff'
    body = client.get('/').get_data(as_text=True)
    group = body.split('add-student-courses')[1].split('</div>')[0]
    assert 'CPS109' in group and 'CPS213' in group
