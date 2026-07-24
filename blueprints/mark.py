"""The staff marking page and its per-tap save endpoint."""
from flask import Blueprint, url_for
from myhtml import *
import db
from common import userCas, page_header

mark_bp = Blueprint('mark', __name__)

# Buttons shown per competency on the marking page, in display order.
# The value is what gets POSTed to /save; 'unassessed' deletes the row.
MARK_BUTTONS = [
    ('unassessed', 'Not assessed'),
    ('achieved', 'Achieved'),
    ('cooling_off', 'Not passed'),
]


@mark_bp.route('/mark/<student_number>')
def mark_student(student_number=None):
    user, casUser = userCas()
    p = page()
    p.setJs('/static/js/mark.js')
    p += page_header()
    with db.cursor() as sql:
        student = sql.execute(
            "select first_name, last_name from students where student_number = ?",
            (student_number,)
        ).fetchone()
        if student is None:
            p += h1('Student not found')
            return str(p)
        first, last = student
        p += h1('Marking: ' + first + ' ' + last)
        p += div(
            a('← Back to students', href=url_for('main.index')).classes('back-link'),
            a('View as student', href=url_for('main.view_student', student_number=student_number)).classes('back-link'),
        ).classes('subnav')
        # current recorded state per competency: competency_id -> status
        states = {
            row[0]: row[1]
            for row in sql.execute(
                "select competency_id, status from achievements where student_number = ?",
                (student_number,)
            ).fetchall()
        }
        # one segmented button group per competency. Tapping a button sets
        # that state and saves it (see static/js/mark.js). No Save button.
        current_course = None
        for (cid, name, course) in sql.execute(
                "select id, name, course from competencies order by id").fetchall():
            # Heading per course so a TA marking sees the 80 items in two labelled
            # blocks (CPS109, then CPS213) instead of one long run.
            if course != current_course:
                p += h2(course or 'Other')
                current_course = course
            current = states.get(cid, 'unassessed')
            group = div().classes('mark-group')
            for (value, label) in MARK_BUTTONS:
                # str(cid): myhtml renders v==True as a valueless attribute,
                # and in Python the int 1 == True, so id 1 would lose its value.
                b = button(label, type='button',
                           data_student=student_number,
                           data_competency=str(cid),
                           data_state=value).classes('mark-btn')
                active = (value == current)
                if active:
                    b.addClasses('is-active')
                b.addAttributes(aria_pressed='true' if active else 'false')
                group += b
            p += div(div(name).classes('mark-label'), group).classes('mark-row')
    return str(p)


@mark_bp.route('/save/<student_number>/<competency_id>/<new_state>', methods=['POST'])
def save_mark(student_number, competency_id, new_state):
    # Runs on every tap of a competency. Makes the database match the tap:
    #   tapped to unassessed   -> remove the record (undo it, like it never happened)
    #   tapped to achieved     -> save it as achieved
    #   tapped to cooling_off  -> save it as cooling off
    # Each tap saves on its own, no Save button.
    with db.cursor() as sql:
        if new_state == 'unassessed':
            sql.execute(
                "delete from achievements where student_number = ? and competency_id = ?",
                (student_number, competency_id)
            )
        else:
            sql.execute(
                "insert or replace into achievements (student_number, competency_id, status, date_recorded) values (?, ?, ?, CURRENT_TIMESTAMP)",
                (student_number, competency_id, new_state)
            )
    return ''
