# Deployment

How to install and run this. Live status of what is outstanding is on #4, not here.

Three pieces, and two words that come up throughout:

- **Apache** is the web server. Its config for one site is called a **vhost**, short for
  virtual host, and one machine can serve several.
- **mod_wsgi** is the adapter that lets Apache run a Python app. WSGI is just the name
  of the handover between them. `wsgi.py` is the one-line file that hands over our app.
- **mod_auth_cas** puts TMU login in front, so Apache checks who you are before the app
  ever sees the request.

## Where it runs

**https://admin.cs.torontomu.ca/studio1**, alongside the existing `/courses` on the same
host (Dave, #4). That host already has LetsEncrypt and already has CAS, so no server,
DNS or certificate request is needed.

Mounted at `/studio1`, not at the root. No code change needed: `WSGIScriptAlias` tells
Flask about the prefix and it adjusts every link automatically.

The CAS service is registered for this URL with SAML 1.1 and the `studentnumber`
attribute.

## Identity

CAS sends two headers and the app needs both:

| Header | Carries |
|--------|---------|
| `Cas-User` | TMU username, e.g. `achen`. Staff resolve from this, since their username is the admin key. |
| `CAS-studentnumber` | student number. Students resolve from this. |

`Cas-User` never contains the student number, whatever attributes are released.

> **Attributes only arrive through SAML validation, and that is our config, not CCS's.**
> CCS confirmed their end is identical for SAML 1.1 and CAS 2.0/3.0, so the protocol on
> the registration does not matter. What matters is the vhost: `CASValidateSAML On` with
> `CASValidateURL` pointing at `/cas/samlValidate`. Point it at `serviceValidate`
> instead and login works perfectly while `studentnumber` never arrives.
>
> **Staff are unaffected** by that, so every check a staff account can run would pass and
> the failure would surface on the first day of class.

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

3. **Staff list.** See **Who gets in** below. Nothing is seeded, and a missing name
   locks that person out silently.
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

## Who gets in

Nobody is added automatically. Two separate lists, and being missing from either looks
the same from the outside: the person signs in through CAS successfully, comes back, and
is bounced to the login page as an unrecognised user. No error, nothing in a log, no
screen anywhere that lists who is missing. It surfaces when that person tries.

**Staff** are the `admins` setting: one space-separated list of **CAS usernames**, not
student numbers. A TA who is also a student still goes here, and staff wins, so they get
the marking screens rather than a student view.

Fill this in and keep it current. It is the deployment's one hand-maintained list.

| Person | Role | CAS username |
| --- | --- | --- |
| Dave Mason | Instructor | `dmason` |
| Sarah Hassan | TA | `s59hassa` |
|  | TA |  |
|  | TA |  |
|  | TA |  |

```
sqlite3 course-data.db "update settings set value = 'dmason s59hassa ...' where key = 'admins'"
```

**Students** are the `students` table, loaded from a class list export:

```
./venv/bin/python import_roster.py classlist.csv --course CPS109 --apply
```

An empty roster locks out every student at once, which is the same silent failure at
scale. Run the importer for both courses.

Adding someone later needs no deploy. Both are data: one is a settings row, the other is
a re-run of the importer, and either takes effect on the next page load.

## Check it works, right after installing

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

**Settings, changed without a deploy.** These are rows, not code. Edit one and it is
live on the next page load: no restart, no `git pull`, no reload. Handy mid-term.

| Setting | Now | What it does |
| --- | --- | --- |
| `daily_cap` | 3 | Competencies a student may book per session. Dave's plan is to raise this to 4 once the pace is clear. |
| `studio_lookahead` | 6 | How many future sessions they can book into. About two weeks. |
| `claim_timeout_minutes` | 20 | When an abandoned claim returns to the queue. |
| `lab_host_pattern` | `eng\d{3}-\d+` | Which machines count as the studio lab, for seat entry. Widen it to relax the gate in an emergency. |

```
sqlite3 course-data.db "update settings set value = '4' where key = 'daily_cap'"
```

A student already carrying missed sessions gets more than the cap on purpose, so the
number they see is not always this one.

**Rolling back a bad deploy.** Code only, and it is as fast as deploying:
```
git log --oneline -5
git checkout <previous-commit>
touch wsgi.py
```
If the bad deploy included a migration, restore the dated backup as well. That is why
`migrate.py --apply` takes one before touching anything.

**When something breaks, look here first.** The app has no log of its own; under
`mod_wsgi` everything Flask writes goes to Apache's error log:
```
tail -f /var/log/apache2/error.log
```
A Python traceback there is an app bug. A CAS or `mod_auth_cas` message is a config
problem, and the identity section above is where to start.
