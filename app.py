from contextlib import closing
import sqlite3
from flask import Flask, request, url_for
from myhtml import *

app = Flask(__name__)
app.config['ENV'] = 'development'
STATE_LABELS = {
    'achieved': 'Achieved',
    'not_yet': 'Not yet',
    'cooling_off': 'Cooling off',
}

# Buttons shown per competency on the marking page, in display order.
# The value is what gets POSTed to /save; 'blank' deletes the row.
MARK_BUTTONS = [
    ('blank', 'Not yet'),
    ('achieved', 'Achieved'),
    ('cooling_off', 'Cooling off'),
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

def achievement_state(competency_id, states):
    # states maps competency_id -> recorded status. No row means 'not_yet'.
    return states.get(competency_id, 'not_yet')


@app.route('/mark')
def mark():
    user, casUser = userCas()
    p = page()
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            for (number, first, last) in sql.execute(
                    "select student_number, first_name, last_name from students order by last_name").fetchall():
                p += div(a(last + ", " + first, href=url_for('mark_student', student_number=number)))
    return str(p)


@app.route('/mark/<student_number>')
def mark_student(student_number=None):
    user, casUser = userCas()
    p = page()
    p.setJs('/static/js/mark.js')
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
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
                current = states.get(cid, 'blank')
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
    #   tapped to blank        -> remove the record (undo it, like it never happened)
    #   tapped to achieved     -> save it as achieved
    #   tapped to cooling_off  -> save it as cooling off
    # Each tap saves on its own, no Save button.
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            if new_state == 'blank':
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
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            states = {
                row[0]: row[1]
                for row in sql.execute(
                    "select competency_id, status from achievements where student_number = ?",
                    (student_number,)
                ).fetchall()
            }
            for (cid, name) in sql.execute(
                "select id, name from competencies order by id"
            ).fetchall():
                state = achievement_state(cid, states)
                p += div(name + " " + STATE_LABELS[state])
    return str(p)