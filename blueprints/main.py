"""The roster home page and the read-only student progress view."""
from flask import Blueprint, url_for, redirect
from myhtml import *
import db
import logic
from common import current_user, userCas, page_header

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    user, role = current_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if role == 'student':
        return redirect(url_for('main.view_student', student_number=user))
    p = page()
    p += page_header()
    p += h1('Students')
    p += div(a('Queue →', href=url_for('queue.queue'))).classes('subnav')
    with db.cursor() as sql:
        for (number, first, last) in sql.execute(
                "select student_number, first_name, last_name from students order by last_name").fetchall():
            # one roster row per student: name plus a Mark and a View link
            p += div(
                span(last + ", " + first).classes('roster-name'),
                a('Mark', href=url_for('mark.mark_student', student_number=number)).classes('roster-link'),
                a('View', href=url_for('main.view_student', student_number=number)).classes('roster-link'),
            ).classes('roster-row')
    return str(p)


@main_bp.route('/view/<student_number>')
def view_student(student_number=None):
    user, casUser = userCas()
    p = page()
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
        p += h1('Progress: ' + first + ' ' + last)
        cur_user, cur_role = current_user()
        nav = div().classes('subnav')
        nav += a('← Back to students', href=url_for('main.index')).classes('back-link')
        if cur_role == 'student' and cur_user == student_number:
            nav += a('Join queue →', href=url_for('queue.queue'))
        p += nav
        states = {}
        recorded_at = {}
        for (cid, status, recorded) in sql.execute(
            "select competency_id, status, date_recorded from achievements where student_number = ?",
            (student_number,)
        ).fetchall():
            states[cid] = status
            recorded_at[cid] = recorded
        for (cid, name) in sql.execute(
            "select id, name from competencies order by id"
        ).fetchall():
            state = logic.achievement_state(cid, states)
            if state == 'cooling_off':
                state_label = logic.cooling_off_label(recorded_at.get(cid))
            else:
                state_label = logic.STATE_LABELS[state]
            p += div(
                span(name).classes('progress-name'),
                span(state_label).classes('progress-badge').addClasses('state-' + state),
            ).classes('progress-row')
    return str(p)
