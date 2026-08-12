"""Helpers shared across blueprints: identity and the page header.

Kept separate so every blueprint can import these without importing each other
(which would create circular imports).
"""
from flask import session, request, url_for, current_app
from myhtml import *


# Dev mode hardcodes the user to dmason so no CAS/Apache is needed locally.
# In production, Apache mod_auth_cas sets the Cas-User header.
def userCas(user=None):
    if current_app.config.get('ENV') == 'development':
        casUser = 'dmason'
    if 'Cas-User' in request.headers:
        casUser = request.headers['Cas-User']
    if not user:
        user = casUser
    return user, casUser


def current_user():
    # Interim session-based identity (CAS replaces this later). Returns (user, role).
    return session.get('user'), session.get('role')


def page_header():
    # Banner on every page: title links home, plus who you're signed in as.
    # Endpoint names are blueprint-qualified now: 'main.index', 'auth.login'.
    header = div().classes('site-header')
    header += a('Competency Tracker', href=url_for('main.index')).classes('site-title')
    user, role = current_user()
    if user:
        header += span('Signed in as ' + user + ' (' + role + ')').classes('whoami')
        header += a('Switch user', href=url_for('auth.login')).classes('back-link')
    if role == 'staff':
        # A second row of nav links, below the sign-in info, so every staff view is
        # reachable from anywhere without crowding the identity row.
        nav = div().classes('staff-nav')
        nav += a('Queue', href=url_for('queue.queue')).classes('staff-nav-link')
        nav += a('Students', href=url_for('main.index')).classes('staff-nav-link')
        nav += a('Attendance', href=url_for('main.attendance')).classes('staff-nav-link')
        nav += a('Shout-outs', href=url_for('main.endorsements')).classes('staff-nav-link')
        header += nav
    return header
