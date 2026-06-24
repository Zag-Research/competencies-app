"""Sign in / sign out (interim dev login until CAS)."""
from flask import Blueprint, request, url_for, session, redirect
from myhtml import *
import db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        role = db.lookup_role(username)
        if role is None:
            error = '"' + username + '" is not a known staff username or student number.'
        else:
            session['user'] = username
            session['role'] = role
            if role == 'staff':
                return redirect(url_for('queue.queue'))
            return redirect(url_for('main.view_student', student_number=username))
    # GET, or a failed POST: show the sign-in form
    p = page()
    p += div(a('Competency Tracker', href=url_for('auth.login')).classes('site-title')).classes('site-header')
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


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
