"""Does the app's competency list still match the document? (#114, #98)

    ./venv/bin/python check_competencies.py CPS213.txt --course CPS213

Read only. It never writes to the database, so running it is always safe.

Why this exists. The list lives in a Google Doc that Dave and Jonathan edit during the
term, and the app has its own copy. They drifted once already without anyone noticing:
CPS213 had 40 competencies and the document had 40, but they were not the same 40,
because a sub-point had been promoted into a competency of its own. Everything after it
was numbered one higher in the app than in the document for three months.

The count matching is exactly what hid it, so this compares position by position and
reports anything that does not line up.

Give it a plain text export of the document: in Google Docs, File, Download, Plain text.
"""
import argparse
import os
import re
import sqlite3
import sys

DB_PATH = os.environ.get('DB_PATH', 'course-data.db')
# A competency line in the document: "12. Produces a conditional structure..."
NUMBERED = re.compile(r'^\s*(\d+)\.\s+(.*)$')
# A sub-point: "a. Uses an if-elif-else structure". Ignored here, the app stores those
# separately and a mismatch in them is not the same problem as a mismatch in the list.
SUBPOINT = re.compile(r'^\s*(?:[a-z]|[ivx]+)\.\s')


def read_document(path):
    """The numbered competencies, in order, as [(number, title)].

    Wrapped lines continue the item above, which is how a text export of a Google Doc
    comes out for anything longer than a line.
    """
    items = []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line.strip():
            continue
        match = NUMBERED.match(line)
        if match:
            items.append([int(match.group(1)), match.group(2).strip()])
        elif SUBPOINT.match(line):
            continue
        elif items and line.startswith((' ', '\t')) or (items and not line[0].isdigit()):
            items[-1][1] += ' ' + line.strip()
    return [(n, t) for n, t in items]


def read_app(course):
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            'select name from competencies where course = ? order by id', (course,)
        ).fetchall()
    finally:
        connection.close()
    return [(i + 1, r[0]) for i, r in enumerate(rows)]


def normalise(text):
    """Compare meaning, not punctuation. Curly quotes and trailing colons are noise."""
    text = text.lower().replace('’', "'").replace('‘', "'")
    text = re.sub(r'[^a-z0-9\' ]+', ' ', text)
    return ' '.join(text.split())


def compare(document, app):
    """Line the two lists up by position and say where they stop agreeing.

    Deliberately does not guess whether a mismatch is a rewording or a different
    competency. Text similarity cannot tell those apart here: "Decoders" and "Encoders"
    score higher than a genuine rephrasing of the same competency does. A wrong label
    would be worse than none, because somebody would trust it. Both texts are printed
    and the person reading decides.
    """
    findings = []
    for i in range(max(len(document), len(app))):
        doc = document[i][1] if i < len(document) else None
        got = app[i][1] if i < len(app) else None
        position = i + 1
        if doc is None:
            findings.append((position, 'extra in the app', '', got))
        elif got is None:
            findings.append((position, 'missing from the app', doc, ''))
        elif normalise(doc) != normalise(got):
            findings.append((position, 'does not match', doc, got))
    return findings


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', help='plain text export of the competency document')
    parser.add_argument('--course', required=True, help='e.g. CPS109')
    args = parser.parse_args(argv)

    document = read_document(args.document)
    app = read_app(args.course)
    print('%s: %d in the document, %d in the app\n' % (args.course, len(document), len(app)))

    findings = compare(document, app)
    if not findings:
        print('They match, position for position.')
        return 0

    # The first mismatch is usually the cause and everything below it the consequence,
    # so lead with it rather than making somebody read the whole list to find it.
    first = findings[0]
    print('First difference is at position %d. Everything below may follow from it.\n'
          % first[0])
    for position, kind, doc, got in findings:
        print('  %2d  %s' % (position, kind))
        if doc:
            print('        document: %s' % doc[:78])
        if got:
            print('        app:      %s' % got[:78])
    print('\n%d position(s) do not match.' % len(findings))
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
