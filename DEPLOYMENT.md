# Deployment

Getting the app live at TMU: Apache + `mod_wsgi` running the Flask app, with TMU **CAS**
(central login) in front via `mod_auth_cas`. The **code is deployment-ready** (see the
checklist below); the parts that take real calendar time are the requests to other people,
so start those first.

## Where this runs

**https://admin.cs.torontomu.ca/studio1** — decided by Dave on #4 (Aug 18). It parallels
the existing `https://admin.cs.torontomu.ca/courses`.

Three things that were expected to take weeks turn out to be already done on that host:

- the machine exists, so no server request and no DNS entry are needed
- LetsEncrypt is already set up, so the `https` the CAS registration requires is in place
- CAS already points at the same host for `/courses`

**So there is exactly one outstanding request: submit the production CAS registration**
(the same Google Form as the test one, linked from
https://www.torontomu.ca/ccs/services/applications/cas/), with:

| Field | Value |
|-------|-------|
| Service URL | `https://admin.cs.torontomu.ca/studio1` |
| Environment | Production — `cas.torontomu.ca` |
| Protocol | CAS 3.0 (needed for attributes) |
| Required attributes | `studentnumber` |
| Hosted at TMU | On Campus |

Its approval turnaround is now the only thing between here and being live, which is why
it goes in before any config work.

### Note on the sub-path

The app is mounted at `/studio1`, not at the root of the host. Nothing in the code has to
change for that: `WSGIScriptAlias /studio1` makes Apache set `SCRIPT_NAME`, and Flask's
`url_for` prefixes every generated URL accordingly. The one thing to check in the smoke
test is that links and form actions come out as `/studio1/...` rather than `/...`.

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
this note).

**A is very likely.** `studentnumber` is one of the attributes the CAS Service Request Form
offers, and it was requested on the test registration (CCS request #667, configured Aug 17).
Their own note says attributes are "subject to approval / privacy impact assessment", so
confirm it is actually being released before assuming A: sign in as a student and check what
`Cas-User` contains. If it is a username rather than a number, switch to B.

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
   # Existing vhost for admin.cs.torontomu.ca; this app is one location within it,
   # alongside /courses.
   <VirtualHost *:443>
       ServerName admin.cs.torontomu.ca

       <Location /studio1>
           AuthType CAS
           Require valid-user
           # mod_auth_cas must SET Cas-User itself and strip any client-supplied one.
           # CAS 3.0 attribute release has to be on, or studentnumber never arrives
           # and identity_from_cas falls back to option B.
       </Location>

       WSGIDaemonProcess studio1 python-home=/var/www/competencies-app/venv
       WSGIProcessGroup studio1
       WSGIScriptAlias /studio1 /var/www/competencies-app/wsgi.py

       SetEnv APP_ENV production
       SetEnv DB_PATH /var/www/competencies-app/course-data.db
       # SECRET_KEY is better set on WSGIDaemonProcess so it isn't world-readable in the vhost.
   </VirtualHost>
   ```

   Do **not** put a reverse proxy in front of this. The lab-machine check (#46) reverse-
   resolves `remote_addr`, so the app has to see the student's real address. CS systems
   confirmed the lab machines have unique routable IPs with no NAT, and a proxy here would
   undo that and make every request look like it came from the server itself.

## Smoke test after deploying

- Visiting any page redirects through TMU CAS and comes back signed in.
- A **staff** account (in the `admins` setting) lands on the queue and can mark.
- A **student** account sees only their own progress (confirms the identity mapping from the
  decision above works).
- Restart Apache: existing sessions still work (confirms `SECRET_KEY` is set, not the dev
  fallback).

## Updating the app after it is live

Code changes are cheap:

```
git pull
touch wsgi.py          # mod_wsgi reloads on the timestamp; no restart needed
```

Schema changes go through migrations. **Never run `schema.sql` against the live
database** — it drops every table, which in production means destroying student results.

```
./venv/bin/python migrate.py            # what is pending
./venv/bin/python migrate.py --apply    # dated backup, then apply
```

`--apply` copies the database to `course-data.db.YYYY-MM-DD` before touching anything, and
that copy is the recovery path if a migration fails halfway. A second run on the same day
reuses the same file, per Dave on #55: a date stamp, no finer granularity. See
`migrations/README.md` for adding one.

Deploy between studio sessions, never during one: a reload mid-marking loses a TA's
in-progress work.

## What's still not automated

- **Term boundaries as a sign-up window.** `TERM_START` / `TERM_END` in `logic.py` bound the
  term for counting the studio's 36 sessions (#50), but sign-up still offers any Tue/Wed/Thu,
  in or out of term. Harmless while the studio isn't running.
- **Backups on a schedule.** The command above is manual. `course-data.db` is a single file,
  so any cron job that copies it with a date stamp will do.
