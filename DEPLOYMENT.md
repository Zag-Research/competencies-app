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
| Protocol | **SAML 1.1** (see below; CAS 3.0 was submitted first and corrected) |
| Required attributes | `studentnumber` |
| Hosted at TMU | On Campus |

Its approval turnaround is now the only thing between here and being live, which is why
it goes in before any config work.

### Note on the sub-path

The app is mounted at `/studio1`, not at the root of the host. Nothing in the code has to
change for that: `WSGIScriptAlias /studio1` makes Apache set `SCRIPT_NAME`, and Flask's
`url_for` prefixes every generated URL accordingly. The one thing to check in the smoke
test is that links and form actions come out as `/studio1/...` rather than `/...`.

## How identity arrives from CAS

CAS sends **two** things, and the app needs both:

| Header | Carries | Set by |
|--------|---------|--------|
| `Cas-User` | the TMU **username**, e.g. `achen` | `mod_auth_cas` via `CASAuthNHeader` |
| `CAS-studentnumber` | the **student number**, e.g. `500111111` | attribute release, named `<CASAttributePrefix><attr>` |

Staff resolve from the first: their CAS username is already the admin key in the `admins`
setting. Students resolve from the second, because this app keys students on the student
number and that is a different string from their username.

**An earlier version of this document was wrong about that.** It claimed CAS could put the
student number into `Cas-User` itself, so nothing would need changing. `mod_auth_cas` does
not work that way: it publishes attributes as their own headers and leaves `CASAuthNHeader`
as the username. Had that gone to production unchanged, no student would have resolved,
and we would have found out on the first day of class.

### Attributes need SAML validation, not CAS 3.0

This is the part most likely to bite, because it fails silently.

`mod_auth_cas` passes attributes to the application only when `CASValidateSAML On` is set
and `CASValidateURL` points at a **SAML** endpoint. Its documentation covers CAS v1, v2 and
SAML 1.1; there is **no CAS v3 support**, so `/p3/serviceValidate` cannot deliver attributes
here however the service is registered.

The first production registration was submitted as CAS 3.0 and corrected to SAML 1.1 on
Aug 18. If it ever gets set back to CAS 3.0, login will still work perfectly and
`studentnumber` will simply never arrive.

Which is the trap: **staff would be completely unaffected.** Their identity comes from
`Cas-User`, which is always present. Every check a staff account can run would pass, and the
failure would appear on the first day of class, as a room of first-years who cannot sign in.

### The header name is ours, not theirs

`CASAttributePrefix` is set in our own Apache vhost, not on CCS's CAS server, so we choose
it. Use `CAS-` (the Apache 2.4 default). Not `CAS_`: Apache 2.4 drops headers containing
underscores, so the old default silently loses every attribute.

That makes `studentnumber` arrive as `CAS-studentnumber`, which is what the
`cas_student_number_header` setting defaults to. If the vhost ever uses a different prefix,
match it with a row update rather than a code change:

```sql
update settings set value = 'CAS-somethingelse' where key = 'cas_student_number_header';
```

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

           # Attributes reach the app ONLY through SAML validation. mod_auth_cas has no
           # CAS v3 support, so /p3/serviceValidate is not an option: without these two
           # lines login still works and studentnumber silently never arrives.
           CASValidateSAML On
           CASValidateURL https://cas.torontomu.ca/cas/samlValidate

           # Publishes the username as Cas-User AND each attribute as a header. Attribute
           # headers are only emitted when this is set.
           CASAuthNHeader Cas-User
           # Header names become <prefix><attr>, so studentnumber -> CAS-studentnumber,
           # which is what the cas_student_number_header setting expects. Do NOT use the
           # old CAS_ default: Apache 2.4 drops headers containing underscores.
           CASAttributePrefix CAS-

           # mod_auth_cas must SET Cas-User itself and strip any client-supplied one.
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
- **A real student account signs in and sees their own progress.** This is the one check
  that cannot be skipped and cannot be done from a staff account. It is the only thing that
  proves SAML validation is on, the attribute is being released, and the header prefix
  matches. If it fails, look at the request headers first: `Cas-User` present but no
  `CAS-studentnumber` means attribute release is not reaching us.
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
