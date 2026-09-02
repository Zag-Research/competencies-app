"""Sign in / sign out.

Two different pages behind one route. In development this is the interim login form,
because there is no CAS locally. In production CAS has already authenticated anyone who
gets here, so the form is meaningless and what they need instead is to be told who CAS
says they are (#90).
"""
from flask import Blueprint, request, url_for, session, redirect, current_app
from myhtml import *
import common
from common import current_user
import db

auth_bp = Blueprint('auth', __name__)


def not_recognised_page():
    """Production. CAS knows this person; the app does not (#90).

    The failure this replaces was silent and shaped like a dead end: an unlisted TA
    signed in through CAS successfully, was bounced to a development login form that
    production ignores, typed something, and was bounced again. Nothing on any screen,
    and nothing in a log, said which identifier the app had actually been handed.

    That mattered because we cannot verify in advance what TMU's CAS puts in `Cas-User`.
    The documentation says a short username. It could be a student number or an email.
    Being wrong locks out every TA including the instructor, on the first morning.

    So the page shows the person their own identifier. Whoever hits it first reads the
    string off the screen, and that exact string goes into the `admins` setting, which
    is a row update and needs no deploy. The guess disappears.

    It also reports whether the student number attribute arrived, because that is the
    one thing only a real student login can prove, and its absence means SAML validation
    is misconfigured rather than anything being wrong with this person.

    Only ever shows somebody their own identity. No other header is read or displayed.
    """
    cas_user = request.headers.get('Cas-User')
    header = common.student_number_header()
    student_number = request.headers.get(header)
    p = page()
    p += div(span('Competency Tracker').classes('site-title')).classes('site-header')
    p += h1('You are signed in, but not on a list')
    p += div('TMU sign-in worked. This app does not recognise the identity it was '
             'given, so it cannot tell whether you are staff or a student.'
             ).classes('subnav')
    rows = div().classes('progress-row')
    rows += span('CAS signed you in as').classes('progress-name')
    rows += span(cas_user or 'nothing at all').classes('progress-badge')
    p += rows
    attr = div().classes('progress-row')
    attr += span(header).classes('progress-name')
    attr += span(student_number or 'not sent').classes('progress-badge').addClasses(
        'state-achieved' if student_number else 'state-cooling_off')
    p += attr
    p += h2('What to do')
    if cas_user and not student_number:
        # Staff never need the attribute, so this combination is exactly the failure
        # DEPLOYMENT.md warns is invisible to every check a staff account can run.
        p += div('No student number arrived. If you are a student, that is a server '
                 'configuration problem, not something you did: CAS is not releasing '
                 'attributes. Send this page to whoever deployed the app.'
                 ).classes('queue-notice')
    p += div('If you are a TA or the instructor, the identifier above needs adding to '
             'the staff list. If you are a student, your student number needs to be in '
             'the roster. Either is a one line change on the server and takes effect '
             'immediately, with no redeploy.').classes('queue-empty')
    return str(p)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # In production CAS has already authenticated whoever reaches this, so there is
    # nothing to sign into. Landing here means the app did not recognise them.
    if current_app.config.get('ENV') == 'production':
        # Somebody the app already knows has no business on this page: it exists to tell
        # an unrecognised person what CAS called them. Showing a valid user "you are not
        # on a list" is alarming and false, so send them home instead (#121).
        if current_user()[0]:
            return redirect(url_for('main.index'))
        return not_recognised_page()
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
