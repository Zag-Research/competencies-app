from contextlib import closing
import sqlite3
from flask import Flask, request, url_for, redirect
from myhtml import *
from datetime import date

app = Flask(__name__)
app.config['ENV'] = 'development'
STATE_LABELS = {
    'achieved': 'Achieved',
    'not_yet': 'Not yet',
    'cooling_off': 'Cooling off',
}

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

def achievement_state(competency_id, achieved):
    if competency_id in achieved:
        return 'achieved'
    else:
        return 'not_yet'


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
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            # which competencies this student has already achieved
            achieved = {
                row[0]
                for row in sql.execute(
                    "select competency_id from achievements where student_number = ?",
                    (student_number,)
                ).fetchall()
            }
            # build a form with one checkbox per competency
            f = form(method='post')
            for (cid, name) in sql.execute(
                    "select id, name from competencies order by id").fetchall():
                box = input(type='checkbox', name=str(cid))
                if cid in achieved:
                    box.addAttributes(checked='checked')
                f += div(box, name)
            f += input(type='submit', value='Save')
            p += f
    return str(p)

@app.route('/mark/<student_number>', methods=['POST'])
def save_marks(student_number):
    submitted = { int(k) for k in request.form }
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            # which competencies this student has already achieved
            stored = {
                row[0]
                for row in sql.execute(
                    "select competency_id from achievements where student_number = ?",
                    (student_number,)
                ).fetchall()
            }

            to_insert = submitted - stored
            to_delete = stored - submitted

            for cid in to_insert:
                sql.execute(
                    "insert into achievements (student_number, competency_id, date_achieved) values (?, ?, ?)",
                    (student_number, cid, date.today())
                )
                
            for cid in to_delete:
                sql.execute(
                    "delete from achievements where student_number = ? and competency_id = ?",
                    (student_number, cid)
                    )
            connection.commit()
            
    return redirect(url_for('mark_student', student_number=student_number))

@app.route('/view/<student_number>')
def view_student(student_number=None):
    user, casUser = userCas()
    p = page()
    with closing(sqlite3.connect("course-data.db")) as connection:
        with closing(connection.cursor()) as sql:
            achieved = {
                row[0]
                for row in sql.execute(
                    "select competency_id from achievements where student_number = ?",
                    (student_number,)
                ).fetchall()
            }
            for (cid, name) in sql.execute(
                "select id, name from competencies order by id"
            ).fetchall():
                state = achievement_state(cid, achieved)
                p += div(name + " " + STATE_LABELS[state])
    return str(p)