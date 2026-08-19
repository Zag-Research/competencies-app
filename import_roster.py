"""Load the real student roster from a class list.

    ./venv/bin/python import_roster.py class-list.csv
    ./venv/bin/python import_roster.py class-list.csv --apply

Without --apply it reports what it would do and changes nothing.

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


def read_rows(path):
    """The CSV as a list of dicts keyed by our column names. Raises on a bad file."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError('that file is empty')
        found = {normalise(name): name for name in reader.fieldnames}
        missing = [c for c in REQUIRED if normalise(c) not in found]
        if missing:
            raise ValueError(
                'missing column(s): ' + ', '.join(missing)
                + '\nthe file has: ' + ', '.join(reader.fieldnames))
        rows = []
        for line, raw in enumerate(reader, start=2):
            row = {c: (raw[found[normalise(c)]] or '').strip() for c in REQUIRED}
            if not any(row.values()):
                continue                       # blank line, common at the end of exports
            blank = [c for c in REQUIRED if not row[c]]
            if blank:
                raise ValueError(
                    'line ' + str(line) + ' is missing ' + ', '.join(blank))
            rows.append(row)
    if not rows:
        raise ValueError('no rows in that file')
    return rows


def plan(connection, rows):
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

    for (number, course), was_withdrawn in current.items():
        if (number, course) not in in_file and was_withdrawn is None:
            withdrawn.append(number + '  ' + course)

    return added, updated, enrolled, returning, withdrawn


def apply(connection, rows, today=None):
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
    for (number, course) in current:
        if (number, course) not in in_file:
            connection.execute(
                'update enrollments set withdrawn_on = ?'
                ' where student_number = ? and course = ?', (today, number, course))
    connection.commit()


def describe(label, items):
    if not items:
        return
    print('\n' + label + ' (' + str(len(items)) + ')')
    for item in items:
        print('  ' + item)


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[0])
        print('usage: import_roster.py <class-list.csv> [--apply]')
        print('needs columns: ' + ', '.join(REQUIRED))
        return 2
    path = argv[0]
    db_path = os.environ.get('DB_PATH', 'course-data.db')
    if not os.path.exists(db_path):
        print('no database at ' + db_path)
        return 1
    try:
        rows = read_rows(path)
    except (OSError, ValueError) as problem:
        print('could not read ' + path + ': ' + str(problem))
        return 1

    connection = sqlite3.connect(db_path)
    try:
        added, updated, enrolled, returning, withdrawn = plan(connection, rows)
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
        apply(connection, rows)
        print('\ndone')
        return 0
    finally:
        connection.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
