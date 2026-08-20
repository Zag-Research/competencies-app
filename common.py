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
        return identity_from_cas(request.headers.get('Cas-User'),
                                 request.headers.get(student_number_header()))
    return session.get('user'), session.get('role')


# Which request header carries the student number CAS releases. mod_auth_cas publishes
# each attribute as <CASAttributePrefix><name>, and the prefix is a server-side config
# choice (its default is CAS_ on Apache 2.2 and CAS- on 2.4; Apache 2.4 drops headers
# containing underscores, so a 2.4 deployment cannot use the old default). A setting, so
# matching whatever CCS configured is a row update rather than a deploy.
DEFAULT_STUDENT_NUMBER_HEADER = 'CAS-studentnumber'


def student_number_header():
    return db.get_setting('cas_student_number_header', DEFAULT_STUDENT_NUMBER_HEADER)


def identity_from_cas(cas_user, student_number=None):
    """Map what CAS told us about this request to (user, role); (None, None) if unknown.

    Two headers, because CAS sends two different things and the app needs both:

    - `Cas-User` is the TMU **username** (mod_auth_cas sets it from CASAuthNHeader). It is
      always present, and for staff it is the whole answer: their CAS username is already
      the admin key.
    - the attribute header carries the **student number**, which is a different string
      from the username. This app keys students on the number, so a student is resolved
      from here, not from Cas-User.

    An earlier version of this assumed CAS could put the number into `Cas-User` itself.
    It cannot: mod_auth_cas publishes attributes as their own headers and leaves
    CASAuthNHeader as the username, so a student would never have resolved in production.

    Staff are checked first. An account that is both (an instructor with a student number
    attached) is staff here, which is the safe way round: it grants them the marking
    screens they need rather than trapping them in a student view.
    """
    if cas_user and db.lookup_role(cas_user) == 'staff':
        return cas_user, 'staff'
    if student_number and db.lookup_role(student_number) == 'student':
        return student_number, 'student'
    return None, None


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
        nav += a('Progress', href=url_for('reports.progress')).classes('staff-nav-link')
        nav += a('Attendance', href=url_for('main.attendance')).classes('staff-nav-link')
        nav += a('Evaluators', href=url_for('main.evaluators')).classes('staff-nav-link')
        nav += a('Shout-outs', href=url_for('main.endorsements')).classes('staff-nav-link')
        nav += a('Worth reading', href=url_for('main.links')).classes('staff-nav-link')
        header += nav
    return header
