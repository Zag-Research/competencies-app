"""The staff marking page and its per-tap save endpoint."""
from flask import Blueprint, url_for, redirect
from myhtml import *
import db
from common import current_user, page_header

mark_bp = Blueprint('mark', __name__)

# The only states /save may write. Anything else is a bad request: the endpoint
# writes straight to achievements, so it must not accept arbitrary status text.
SAVE_STATES = {'unassessed', 'achieved', 'cooling_off'}

# Buttons shown per competency on the marking page, in display order.
# The value is what gets POSTed to /save; 'unassessed' deletes the row.
MARK_BUTTONS = [
    ('unassessed', 'Not assessed'),
    ('achieved', 'Achieved'),
    ('cooling_off', 'Not passed'),
]


@mark_bp.route('/mark/<student_number>')
def mark_student(student_number=None):
    # Staff only: this is the evaluator's marking screen. A student reaching it
    # would see (and, via /save, could set) anyone's results.
    user, role = current_user()
    if user is None or role != 'staff':
        return redirect(url_for('auth.login'))
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
            a('View as student', href=url_for('main.view_student', student_number=student_number)).classes('back-link'),
        ).classes('subnav')
        # current recorded state per competency: competency_id -> status
        # (this page does not need the dates, so recorded_at is discarded)
        states, _ = db.achievement_states(sql, student_number)
        # one segmented button group per competency. Tapping a button sets
        # that state and saves it (see static/js/mark.js). No Save button.
        current_course = None
        # Only the courses this student takes (#11): marking a CPS213 competency
        # for a CPS109-only student would be meaningless.
        for (cid, name, course) in db.competencies_for(sql, student_number):
            # Heading per course so a TA marking sees the items in labelled blocks
            # (CPS109, then CPS213) instead of one long run.
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
    #
    # Staff only, and locked to the three known states. Without this guard any
    # signed-in student could POST their own competencies to 'achieved', or write
    # junk status text, straight into achievements.
    user, role = current_user()
    if user is None or role != 'staff':
        return ('', 403)
    if new_state not in SAVE_STATES:
        return ('', 400)
    with db.cursor() as sql:
        if new_state == 'unassessed':
            db.clear_achievement(sql, student_number, competency_id)
        else:
            db.record_achievement(sql, student_number, competency_id, new_state, user)
    return ''
