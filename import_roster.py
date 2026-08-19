"""Load the real student roster from a class list.

    ./venv/bin/python import_roster.py class-list.csv
    ./venv/bin/python import_roster.py class-list.csv --apply

Without --apply it reports what it would do and changes nothing.

A class list exported from one course has no course column, because the export happens
from inside that course and it is implied. So pass it in:

    ./venv/bin/python import_roster.py cps109.csv --course CPS109 --apply
    ./venv/bin/python import_roster.py cps213.csv --course CPS213 --apply

Careful: with --course, a student missing from the file is only treated as having
dropped THAT course. Their other course is untouched, which is what you want when
importing one course's list at a time.

Students can add a course until the middle of September and drop until late November,
so this is not a one-time load. It is designed to be re-run against a fresh export as
often as the roster moves.

It never deletes. A student missing from a later export has dropped, and their
competency results have to survive that: a drop can be reversed, and the results cannot
be recreated. So a drop marks `enrollments.withdrawn_on` and leaves everything else
alone. Re-appearing in a later export clears the mark and restores them exactly.

Standalone, no Flask, so it can be run on the server by someone who has never seen this
codebase. See #61.
"""
import csv
import os
import sqlite3
import sys
from datetime import date

# What the CSV needs. Names are matched case-insensitively and ignoring spaces and
# underscores, so "Student Number", "student_number" and "studentnumber" all work.
REQUIRED = ('student_number', 'first_name', 'last_name', 'course')


def normalise(name):
    return name.strip().lower().replace(' ', '').replace('_', '')


def read_rows(path, course=None):
    """The CSV as a list of dicts keyed by our column names. Raises on a bad file.

    `course` supplies the column for a single-course export, which is what D2L produces:
    the export happens from inside one course, so the course itself is never in the file.
    """
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError('that file is empty')
        found = {normalise(name): name for name in reader.fieldnames}
        needed = [c for c in REQUIRED if not (c == 'course' and course)]
        missing = [c for c in needed if normalise(c) not in found]
        if missing:
            raise ValueError(
                'missing column(s): ' + ', '.join(missing)
                + '\nthe file has: ' + ', '.join(reader.fieldnames))
        rows = []
        for line, raw in enumerate(reader, start=2):
            row = {c: (raw[found[normalise(c)]] or '').strip() for c in needed}
            if not any(row.values()):
                continue                       # blank line, common at the end of exports
            if course:
                row['course'] = course
            blank = [c for c in REQUIRED if not row[c]]
            if blank:
                raise ValueError(
                    'line ' + str(line) + ' is missing ' + ', '.join(blank))
            rows.append(row)
    if not rows:
        raise ValueError('no rows in that file')
    return rows


def plan(connection, rows, course=None):
    """What importing `rows` would change, without changing anything.

    Returns (added, updated, enrolled, returning, withdrawn) where each is a list of
    strings describing one change, so the caller can print them and a human can sanity
    check the file before it touches the database.
    """
    added, updated, enrolled, returning, withdrawn = [], [], [], [], []

    existing = {n: (f, l) for (n, f, l) in connection.execute(
        'select student_number, first_name, last_name from students')}
    current = {(n, c): w for (n, c, w) in connection.execute(
        'select student_number, course, withdrawn_on from enrollments')}

    in_file = set()
    for row in rows:
        number, first, last, course = (row['student_number'], row['first_name'],
                                       row['last_name'], row['course'])
        in_file.add((number, course))
        if number not in existing:
            added.append(number + '  ' + first + ' ' + last)
            existing[number] = (first, last)
        elif existing[number] != (first, last):
            was = existing[number]
            updated.append(number + '  ' + was[0] + ' ' + was[1]
                           + ' -> ' + first + ' ' + last)
        if (number, course) not in current:
            enrolled.append(number + '  ' + course)
        elif current[(number, course)] is not None:
            returning.append(number + '  ' + course)

    for (number, enrolled_course), was_withdrawn in current.items():
        # With --course, only that course's absences count as drops. A student missing
        # from the CPS109 list has not dropped CPS213, they were simply never in this file.
        if course and enrolled_course != course:
            continue
        if (number, enrolled_course) not in in_file and was_withdrawn is None:
            withdrawn.append(number + '  ' + enrolled_course)

    return added, updated, enrolled, returning, withdrawn


def apply(connection, rows, today=None, course=None):
    today = (today or date.today()).isoformat()
    in_file = set()
    for row in rows:
        number, first, last, course = (row['student_number'], row['first_name'],
                                       row['last_name'], row['course'])
        in_file.add((number, course))
        # insert or replace on the student number, so re-running with a corrected name
        # fixes it and re-running with the same file changes nothing.
        connection.execute(
            'insert or replace into students (student_number, first_name, last_name)'
            ' values (?, ?, ?)', (number, first, last))
        connection.execute(
            'insert or replace into enrollments (student_number, course, withdrawn_on)'
            ' values (?, ?, null)', (number, course))
    # Anyone previously enrolled and no longer in the file has dropped. Marked, never
    # deleted: their achievements and evaluations stay exactly as they are.
    current = connection.execute(
        'select student_number, course from enrollments where withdrawn_on is null'
    ).fetchall()
    for (number, enrolled_course) in current:
        if course and enrolled_course != course:
            continue
        if (number, enrolled_course) not in in_file:
            connection.execute(
                'update enrollments set withdrawn_on = ?'
                ' where student_number = ? and course = ?',
                (today, number, enrolled_course))
    connection.commit()


def single_course_students(connection):
    """Students enrolled in only one course, as (number, name, course).

    Dave's rule for the pilot is that everyone takes both, so this is almost always the
    sign that only one course's list has been imported. That failure is otherwise
    silent: those students would simply never see the other course's competencies and
    could not sign up for them, and the app would look like it was working.

    Not an error, because #11 genuinely supports a part-time student in one course. A
    warning, so a human decides which it is.
    """
    return connection.execute(
        """select e.student_number, s.first_name || ' ' || s.last_name, e.course
             from enrollments e
             join students s on s.student_number = e.student_number
            where e.withdrawn_on is null
            group by e.student_number
           having count(*) = 1
            order by s.last_name"""
    ).fetchall()


def describe(label, items):
    if not items:
        return
    print('\n' + label + ' (' + str(len(items)) + ')')
    for item in items:
        print('  ' + item)


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[0])
        print('usage: import_roster.py <class-list.csv> [--course CPS109] [--apply]')
        print('needs columns: ' + ', '.join(REQUIRED))
        print('--course supplies the course for a single-course export, which is what')
        print('D2L gives you, since the export happens from inside one course')
        return 2
    path = argv[0]
    course = None
    if '--course' in argv:
        at = argv.index('--course')
        if at + 1 >= len(argv):
            print('--course needs a course name, e.g. --course CPS109')
            return 2
        course = argv[at + 1]
    db_path = os.environ.get('DB_PATH', 'course-data.db')
    if not os.path.exists(db_path):
        print('no database at ' + db_path)
        return 1
    try:
        rows = read_rows(path, course)
    except (OSError, ValueError) as problem:
        print('could not read ' + path + ': ' + str(problem))
        return 1

    connection = sqlite3.connect(db_path)
    try:
        added, updated, enrolled, returning, withdrawn = plan(connection, rows, course)
        print(str(len(rows)) + ' rows in ' + path + ', against ' + db_path)
        describe('new students', added)
        describe('name changed', updated)
        describe('new enrollments', enrolled)
        describe('returning after a drop', returning)
        describe('dropped (marked, not deleted)', withdrawn)
        if not any((added, updated, enrolled, returning, withdrawn)):
            print('\nnothing to change')
            return 0
        if '--apply' not in argv:
            print('\nre-run with --apply to make these changes')
            return 0
        apply(connection, rows, course=course)
        print('\ndone')
        alone = single_course_students(connection)
        if alone:
            print('\nWARNING: ' + str(len(alone)) + ' student(s) are in only one course:')
            for (number, name, in_course) in alone[:10]:
                print('  ' + number + '  ' + name + '  ' + in_course + ' only')
            if len(alone) > 10:
                print('  ... and ' + str(len(alone) - 10) + ' more')
            print('\nIf everyone takes both courses, the other list has not been'
                  ' imported yet.')
            print('Those students cannot sign up for the missing course at all.')
        return 0
    finally:
        connection.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
