# Deployment

Getting the app live at TMU: Apache + `mod_wsgi` running the Flask app, with TMU **CAS**
(central login) in front via `mod_auth_cas`. The **code is deployment-ready** (see the
checklist below); the parts that take real calendar time are the requests to other people,
so start those first.

## Start these now (they gate the timeline)

These depend on TMU IT / whoever owns the server, and their turnaround, not the code, is
what stretches deployment past a day. Kick them off before touching config:

1. **A server / host.** Who provisions it (Dave, the Zag lab, TMU IT)? Need SSH access, and
   Python 3.11+ available.
2. **CAS registration.** Ask TMU IT to register the app's URL with CAS so `mod_auth_cas`
   can authenticate against it. **This is the long-pole item.** Ask specifically: *does CAS
   release the student number as an attribute, or only the TMU username?* — that answers the
   one open decision below.
3. **Network access.** A hostname/DNS entry, and VPN access if the server is inside TMU's
   network.

## The one decision to settle: student identity

Staff already work: their CAS username is the admin key (the `admins` setting), so
`identity_from_cas` resolves them to `staff` with no extra work.

Students are the open piece. Today a student signs in with their **student number**, but CAS
will give their **TMU username**, which is not the same string. Two ways to bridge it:

- **A. CAS releases the student number** as an attribute. Then Apache sets `Cas-User` to the
  number and nothing else changes, `identity_from_cas` already treats `Cas-User` as the
  student key.
- **B. Add a `cas_username` column** to `students`, populated from the course roster, and
  look the student up by it.

The single place to adjust is `identity_from_cas` in `common.py` (one function, marked with
this note). Pick A or B once TMU IT answers question 2 above.

## Server setup (checklist)

Once you have the server and CAS is registered:

1. **Get the code + dependencies**
   ```
   git clone <repo> /var/www/competencies-app && cd /var/www/competencies-app
   python3 -m venv venv && ./venv/bin/pip install -r requirements.txt mod_wsgi
   ```
2. **Build the database** (schema, then the real roster/competencies once #2 lands)
   ```
   sqlite3 /var/www/competencies-app/course-data.db < schema.sql
   ```
3. **File permissions** — SQLite needs the Apache user to write both the DB file **and its
   directory** (for the temporary journal), or you get "readonly database" errors:
   ```
   chown www-data:www-data /var/www/competencies-app /var/www/competencies-app/course-data.db
   ```
4. **Environment** — set these for the app (e.g. in the Apache vhost with `SetEnv`, or the
   WSGI process environment):
   | Variable | Value |
   |----------|-------|
   | `APP_ENV` | `production` — switches identity from the dev `/login` to CAS |
   | `SECRET_KEY` | a long random string, so sessions survive restarts |
   | `DB_PATH` | absolute path to `course-data.db` (the working dir isn't the project folder under Apache) |
5. **Apache vhost** — protect the app with CAS and hand requests to `wsgi.py`:
   ```apache
   <VirtualHost *:443>
       ServerName competencies.example.torontomu.ca

       <Location />
           AuthType CAS
           Require valid-user
           # mod_auth_cas must SET Cas-User itself and strip any client-supplied one.
       </Location>

       WSGIDaemonProcess competencies python-home=/var/www/competencies-app/venv
       WSGIProcessGroup competencies
       WSGIScriptAlias / /var/www/competencies-app/wsgi.py

       SetEnv APP_ENV production
       SetEnv DB_PATH /var/www/competencies-app/course-data.db
       # SECRET_KEY is better set on WSGIDaemonProcess so it isn't world-readable in the vhost.
   </VirtualHost>
   ```

## Smoke test after deploying

- Visiting any page redirects through TMU CAS and comes back signed in.
- A **staff** account (in the `admins` setting) lands on the queue and can mark.
- A **student** account sees only their own progress (confirms the identity mapping from the
  decision above works).
- Restart Apache: existing sessions still work (confirms `SECRET_KEY` is set, not the dev
  fallback).

## What's still not automated

- **Term boundaries.** The studio skips reading weeks, but still offers out-of-term Tue/Wed/Thu
  (summer, between terms). Harmless while the studio isn't running; load real term ranges into
  `logic.py` if it ever matters.
- **Backups.** `course-data.db` is a single file, copy it on a schedule.
