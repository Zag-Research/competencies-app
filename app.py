from contextlib import closing
import sqlite3
from datetime import datetime, timedelta, timezone
from flask import Flask, request, url_for, session, redirect
from myhtml import *

app = Flask(__name__)
app.config['ENV'] = 'development'
# Dev-only secret so Flask can sign session cookies. Use a real secret in production.
app.secret_key = 'dev-only-change-me'
STATE_LABELS = {
    'achieved': 'Achieved',
    'unassessed': 'Not assessed',
    'cooling_off': 'Available to retry',
}

# Buttons shown per competency on the marking page, in display order.
# The value is what gets POSTed to /save; 'unassessed' deletes the row.
MARK_BUTTONS = [
    ('unassessed', 'Not assessed'),
    ('achieved', 'Achieved'),
    ('cooling_off', 'Not passed'),
]

# Dev mode hardcodes the user to dmason so no CAS/Apache is needed locally.
# In production, Apache mod_auth_cas sets the Cas-User header.
def userCas(user=None):
    if app.config['ENV'] == 'development':
        casUser = 'dmason'
    if 'Cas-User' in request.headers:
        casUser = request.headers['Cas-User']
    if not user:
        user = casUser
    return user, casUser

def current_user():
    # Interim session-based identity (CAS replaces this later). Returns (user, role).
    return session.get('user'), session.get('role')

def lookup_role(username):
    # Interim role lookup: 'staff' if listed in the 'admins' setting, else
    # 'student' if it matches a student_number, else None (unrecognized).
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            row = sql.execute(
                "select value from settings where key = 'admins'").fetchone()
            admins = row[0].split() if row else []
            if username in admins:
                return 'staff'
            student = sql.execute(
                "select student_number from students where student_number = ?",
                (username,)
            ).fetchone()
            if student:
                return 'student'
    return None

def achievement_state(competency_id, states):
    # states maps competency_id -> recorded status. No row means 'unassessed'.
    return states.get(competency_id, 'unassessed')


# How long a "Not passed" attempt keeps a competency in cooling off.
# Display only for now: nothing enforces a retry block yet.
COOLDOWN = timedelta(hours=48)

def parse_timestamp(value):
    # date_recorded is stored as UTC text by SQLite CURRENT_TIMESTAMP, and the
    # seed rows omit seconds, so try both formats and tag the result as UTC.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None

def cooling_off_label(date_recorded):
    # Non-negative, student-facing wording (decided June 15: replace "Cooling off").
    recorded = parse_timestamp(date_recorded)
    if recorded is None:
        return STATE_LABELS['cooling_off']
    remaining = COOLDOWN - (datetime.now(timezone.utc) - recorded)
    if remaining <= timedelta(0):
        return 'Available to retry now'
    hours_left = int(remaining.total_seconds() // 3600)
    return 'Available to retry in ' + str(hours_left) + 'h'


def page_header():
    # Banner on every page: title links home, plus who you're signed in as.
    header = div().classes('site-header')
    header += a('Competency Tracker', href=url_for('index')).classes('site-title')
    user, role = current_user()
    if user:
        header += span('Signed in as ' + user + ' (' + role + ')').classes('whoami')
        header += a('Switch user', href=url_for('login')).classes('back-link')
    return header


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        role = lookup_role(username)
        if role is None:
            error = '"' + username + '" is not a known staff username or student number.'
        else:
            session['user'] = username
            session['role'] = role
            if role == 'staff':
                return redirect(url_for('index'))
            return redirect(url_for('view_student', student_number=username))
    # GET, or a failed POST: show the sign-in form
    p = page()
    p += div(a('Competency Tracker', href=url_for('login')).classes('site-title')).classes('site-header')
    p += h1('Sign in')
    p += div('Temporary dev login (CAS replaces this later). Enter a staff '
             'username like "dmason", or a student number to sign in as that '
             'student.').classes('subnav')
    if error:
        p += div(error).classes('login-error')
    f = form(method='post').classes('login-form')
    f += input(type='text', name='username', placeholder='username or student number')
    f += button('Sign in', type='submit').classes('roster-link')
    p += f
    return str(p)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    user, role = current_user()
    if user is None:
        return redirect(url_for('login'))
    if role == 'student':
        return redirect(url_for('view_student', student_number=user))
    p = page()
    p += page_header()
    p += h1('Students')
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            for (number, first, last) in sql.execute(
                    "select student_number, first_name, last_name from students order by last_name").fetchall():
                # one roster row per student: name plus a Mark and a View link
                p += div(
                    span(last + ", " + first).classes('roster-name'),
                    a('Mark', href=url_for('mark_student', student_number=number)).classes('roster-link'),
                    a('View', href=url_for('view_student', student_number=number)).classes('roster-link'),
                ).classes('roster-row')
    return str(p)


@app.route('/mark/<student_number>')
def mark_student(student_number=None):
    user, casUser = userCas()
    p = page()
    p.setJs('/static/js/mark.js')
    p += page_header()
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
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
                a('← Back to students', href=url_for('index')).classes('back-link'),
                a('View as student', href=url_for('view_student', student_number=student_number)).classes('back-link'),
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
            for (cid, name) in sql.execute(
                    "select id, name from competencies order by id").fetchall():
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

@app.route('/save/<student_number>/<competency_id>/<new_state>', methods=['POST'])
def save_mark(student_number, competency_id, new_state):
    # Runs on every tap of a competency. Makes the database match the tap:
    #   tapped to unassessed   -> remove the record (undo it, like it never happened)
    #   tapped to achieved     -> save it as achieved
    #   tapped to cooling_off  -> save it as cooling off
    # Each tap saves on its own, no Save button.
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
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
            connection.commit()
    return ''

@app.route('/view/<student_number>')
def view_student(student_number=None):
    user, casUser = userCas()
    p = page()
    p += page_header()
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            student = sql.execute(
                "select first_name, last_name from students where student_number = ?",
                (student_number,)
            ).fetchone()
            if student is None:
                p += h1('Student not found')
                return str(p)
            first, last = student
            p += h1('Progress: ' + first + ' ' + last)
            p += div(a('← Back to students', href=url_for('index')).classes('back-link')).classes('subnav')
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
                state = achievement_state(cid, states)
                if state == 'cooling_off':
                    label = cooling_off_label(recorded_at.get(cid))
                else:
                    label = STATE_LABELS[state]
                # competency name on the left, a colored status pill on the right
                p += div(
                    span(name).classes('progress-name'),
                    span(label).classes('progress-badge').addClasses('state-' + state),
                ).classes('progress-row')
    return str(p)