"""Helpers shared across blueprints: identity and the page header.

Kept separate so every blueprint can import these without importing each other
(which would create circular imports).
"""
import socket

from flask import session, request, url_for, current_app
from myhtml import *
import db
import logic


# Reverse DNS is a network call sitting in the request path, so resolved names are
# cached. Lab machines are stable and there are only a few dozen, so this costs one
# lookup per machine per process, not one per page view.
_HOSTNAME_CACHE = {}


def request_is_in_lab():
    """True if this request came from a machine in the studio lab (#46).

    The one location-gated action is a student entering their seat number. Everything
    else in the app is open from anywhere, per Dave on #46.

    Method from CS systems: reverse-resolve the caller's address and test the name
    against the lab pattern. The pattern comes from `settings` so the room or its
    naming can change, and so the gate can be relaxed in an emergency, without a
    deploy.

    Development is always treated as in-lab, the same bargain current_user() makes
    with CAS. Requiring a lab machine to work on the app locally would be absurd.

    Failure is treated as "not in the lab". A home address simply has no eng20x-xx
    name, and that is indistinguishable from DNS being unreachable, so the safe
    reading of "I could not resolve this" is "not a lab machine".
    """
    if current_app.config.get('ENV') != 'production':
        return True
    address = request.remote_addr
    hostname = _HOSTNAME_CACHE.get(address)
    if hostname is None:
        try:
            hostname = socket.gethostbyaddr(address)[0]
        except OSError:
            # Not cached: a transient DNS failure must not lock this address out for
            # the life of the process.
            return False
        _HOSTNAME_CACHE[address] = hostname
    return logic.is_lab_host(hostname, db.get_setting('lab_host_pattern'))


def current_user():
    """Who is making this request, as (user, role); (None, None) if not signed in.

    Production identity comes from TMU CAS: Apache's mod_auth_cas authenticates the user
    and sets the Cas-User header, which we trust only in production (Apache must be
    configured to overwrite any client-supplied one). Development uses the interim /login
    session, so no CAS or Apache is needed locally.
    """
    if current_app.config.get('ENV') == 'production':
        return identity_from_cas(request.headers.get('Cas-User'))
    return session.get('user'), session.get('role')


def identity_from_cas(cas_user):
    """Map a TMU CAS username to (user, role); (None, None) if unrecognized.

    Staff resolve directly: their CAS username is already the admin key. Students are the
    one open deployment decision: a student's CAS username is NOT their student_number, so
    either TMU CAS must release the student number (then cas_user already is it), or a
    cas_username column on `students` maps it. Until that is settled this treats cas_user
    as the student key, which is correct for staff and for the CAS-releases-number setup.
    See DEPLOYMENT.md.
    """
    if not cas_user:
        return None, None
    role = db.lookup_role(cas_user)
    return (cas_user, role) if role else (None, None)


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
        nav += a('Evaluators', href=url_for('main.evaluators')).classes('staff-nav-link')
        nav += a('Shout-outs', href=url_for('main.endorsements')).classes('staff-nav-link')
        nav += a('Worth reading', href=url_for('main.links')).classes('staff-nav-link')
        header += nav
    return header
