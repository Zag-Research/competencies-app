# Deployment

Flask under Apache + `mod_wsgi`, with TMU CAS in front via `mod_auth_cas`.
The code is ready. What is left is access and two empty tables.

## Where it runs

**https://admin.cs.torontomu.ca/studio1**, alongside the existing `/courses` on the same
host (Dave, #4). That host already has LetsEncrypt and already has CAS, so no server,
DNS or certificate request is needed.

Mounted at `/studio1`, not at the root. No code change needed for that:
`WSGIScriptAlias /studio1` sets `SCRIPT_NAME` and Flask's `url_for` prefixes every URL.

**Production CAS registration: submitted Aug 18**, as registered:

| Field | Value |
|-------|-------|
| Service URL | `https://admin.cs.torontomu.ca/studio1` |
| Environment | Production, `cas.torontomu.ca` |
| Protocol | SAML 1.1 |
| Required attributes | `studentnumber` |
| Hosted at TMU | On Campus |

Submitted first as CAS 3.0 and corrected the same day, because `mod_auth_cas` cannot
read attributes over CAS v3. If it ever gets set back, see the warning below.

**What is actually outstanding**, in the order it blocks things:

| # | What | Waiting on |
|---|------|-----------|
| 1 | CCS configuring the service for SAML 1.1 (CAS request #667) | Wayne Lyu, CCS |
| 2 | Access to the host, or someone with access doing the install (#4) | Dave |
| 3 | A roster importer. It does not exist yet (#61) | nobody, this is buildable now |
| 4 | The real competency list (#2) | Jonathan |
| 5 | The real roster data, whatever class list can be exported (#61) | Dave |
| 6 | TA CAS usernames for the `admins` setting, step 3 below | hiring closing |

A student account cannot reach the host at all: SSH is filtered from the Student VPN,
and TMU-VPN refuses student accounts. So 2 needs either staff VPN access on top of a
shell account, or the install done by someone who already has both.

Only 3 is code, and it is the one item nothing else blocks.

## Identity

CAS sends two headers and the app needs both:

| Header | Carries |
|--------|---------|
| `Cas-User` | TMU username, e.g. `achen`. Staff resolve from this, since their username is the admin key. |
| `CAS-studentnumber` | student number. Students resolve from this. |

`Cas-User` never contains the student number, whatever attributes are released.

> **Attributes only arrive through SAML validation.** `mod_auth_cas` has no CAS v3
> support. Registered as CAS 3.0, login works perfectly and `studentnumber` never
> arrives. **Staff are unaffected**, so every check a staff account can run would pass
> and the failure would surface on the first day of class.

The header name comes from `CASAttributePrefix`, set in our own vhost. Use `CAS-`.
Never `CAS_`: Apache 2.4 drops headers containing underscores. If the vhost ever uses a
different prefix, match it with a row update rather than a code change:

```sql
update settings set value = 'CAS-somethingelse' where key = 'cas_student_number_header';
```

## Setup

1. **Code**
   ```
   git clone <repo> /var/www/competencies-app && cd /var/www/competencies-app
   python3 -m venv venv && ./venv/bin/pip install -r requirements.txt mod_wsgi
   ```

2. **Database**
   ```
   sqlite3 course-data.db < schema.sql
   ```
   Then load the real competencies (#2) and the real roster (#61). Both tables are
   empty otherwise, and an empty roster means no student can sign in.

3. **Staff list.** `schema.sql` seeds placeholders. Anyone not on this list is bounced
   to the login page, so a missing name locks that TA out completely. Takes **CAS
   usernames**, not student numbers.
   ```
   sqlite3 course-data.db "update settings set value = 'dmason s59hassa ...' where key = 'admins'"
   ```

4. **Permissions.** Apache must be able to write the DB file *and its directory*, or
   you get "readonly database":
   ```
   chown www-data:www-data /var/www/competencies-app /var/www/competencies-app/course-data.db
   ```

5. **Environment**

   | Variable | Value |
   |----------|-------|
   | `APP_ENV` | `production` |
   | `SECRET_KEY` | long random string, so sessions survive restarts |
   | `DB_PATH` | absolute path to `course-data.db` |

6. **Apache.** One Location inside the existing `admin.cs.torontomu.ca` vhost:

   ```apache
   <Location /studio1>
       AuthType CAS
       Require valid-user

       CASValidateSAML On
       CASValidateURL https://cas.torontomu.ca/cas/samlValidate
       CASAuthNHeader Cas-User
       CASAttributePrefix CAS-
   </Location>

   WSGIDaemonProcess studio1 python-home=/var/www/competencies-app/venv
   WSGIProcessGroup studio1
   WSGIScriptAlias /studio1 /var/www/competencies-app/wsgi.py

   SetEnv APP_ENV production
   SetEnv DB_PATH /var/www/competencies-app/course-data.db
   ```

   `mod_auth_cas` must set `Cas-User` itself and strip any client-supplied one.
   Put `SECRET_KEY` on `WSGIDaemonProcess`, not in the vhost, so it is not world-readable.

   No reverse proxy in front. The lab check (#46) reverse-resolves `remote_addr`, and a
   proxy would make every request look like it came from the server.

## Smoke test

- Any page redirects through CAS and comes back signed in.
- Links come out as `/studio1/...`, not `/...`.
- **Every TA** signs in and is staff. A missing name is invisible until that person tries.
- **A real student** signs in and sees their progress. Cannot be done from a staff
  account, and it is the only thing that proves SAML validation, attribute release and
  the header prefix all work. If it fails: `Cas-User` present but no `CAS-studentnumber`
  means attributes are not reaching us.
- Restart Apache, existing sessions survive. Confirms `SECRET_KEY` is set.

## Updating

Code:
```
git pull
touch wsgi.py     # mod_wsgi reloads on the timestamp
```

Schema: **never run `schema.sql` against the live database.** It drops every table.
```
./venv/bin/python migrate.py            # what is pending
./venv/bin/python migrate.py --apply    # dated backup, then apply
```
The backup at `course-data.db.YYYY-MM-DD` is the recovery path if a migration fails
halfway. See `migrations/README.md` to add one.

Deploy between studio sessions. A reload mid-marking loses a TA's in-progress work.

## Not automated

- Sign-up offers any Tue/Wed/Thu, in or out of term. `TERM_START`/`TERM_END` bound the
  term for counting sessions (#50), not for sign-up. Harmless while the studio is closed.
- Backups are manual. Any cron job that copies the file with a date stamp will do.
