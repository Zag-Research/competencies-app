"""The document-versus-app checker (#114).

The list lives in a Google Doc that Dave and Jonathan edit during term, and the app has
its own copy. They drifted once without anyone noticing, and the thing that hid it was
the count still matching. So this compares position by position.
"""
import sqlite3

import pytest

import check_competencies as check


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    path = tmp_path / 'check.db'
    connection = sqlite3.connect(path)
    connection.execute('create table competencies (name TEXT, id INTEGER PRIMARY KEY '
                       'AUTOINCREMENT, description TEXT, course TEXT)')
    for name in ('Alpha', 'Beta', 'Gamma'):
        connection.execute("insert into competencies (name, course) values (?, 'CPS213')",
                           (name,))
    connection.commit(); connection.close()
    monkeypatch.setattr(check, 'DB_PATH', str(path))
    return check


def doc(tmp_path, text):
    p = tmp_path / 'doc.txt'
    p.write_text(text)
    return str(p)


def test_an_identical_list_reports_nothing(app_db, tmp_path):
    path = doc(tmp_path, "1. Alpha\n2. Beta\n3. Gamma\n")
    assert check.compare(check.read_document(path), check.read_app('CPS213')) == []


def test_sub_points_in_the_document_are_not_competencies(app_db, tmp_path):
    """Promoting a sub-point into a competency is exactly the mistake this looks for,
    so the reader must not make it itself."""
    path = doc(tmp_path, "1. Alpha\n   a. first bit\n   b. second bit\n2. Beta\n3. Gamma\n")
    assert [t for _n, t in check.read_document(path)] == ['Alpha', 'Beta', 'Gamma']


def test_a_promoted_sub_point_is_caught(app_db, tmp_path):
    """The real bug: the app split one competency in two, so everything after it shifted
    and the count still looked right."""
    path = doc(tmp_path, "1. Alpha\n2. Gamma\n3. Delta\n")
    findings = check.compare(check.read_document(path), check.read_app('CPS213'))
    assert findings[0][0] == 2                       # first difference at position 2
    assert findings[0][1] == 'does not match'


def test_a_mismatch_shows_both_texts_and_does_not_guess_why(app_db, tmp_path):
    """It does not label a mismatch as a rewording or a replacement.

    Text similarity cannot separate those here: "Decoders" and "Encoders" score higher
    than a genuine rephrasing does. A confident wrong label is worse than none, so both
    texts are printed and the reader decides.
    """
    path = doc(tmp_path, "1. Alpha\n2. Beta\n3. Gamma the third\n")
    findings = check.compare(check.read_document(path), check.read_app('CPS213'))
    assert findings == [(3, 'does not match', 'Gamma the third', 'Gamma')]


def test_punctuation_and_case_are_not_differences(app_db, tmp_path):
    path = doc(tmp_path, "1. alpha.\n2. BETA:\n3. Gamma\n")
    assert check.compare(check.read_document(path), check.read_app('CPS213')) == []


def test_a_missing_or_extra_competency_is_named(app_db, tmp_path):
    path = doc(tmp_path, "1. Alpha\n2. Beta\n3. Gamma\n4. Delta\n")
    findings = check.compare(check.read_document(path), check.read_app('CPS213'))
    assert findings == [(4, 'missing from the app', 'Delta', '')]
