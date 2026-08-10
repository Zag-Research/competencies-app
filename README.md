# Competencies App

A Flask web app for a competency-based studio at TMU (Fall 2026) that runs two
first-year courses together: **CPS109** (Python) and **CPS213** (digital logic).
There are no lectures, assignments, or exams. Instead, students demonstrate
competencies one-on-one to a TA in the lab, and the app coordinates that: students
sign up for what they are ready to show, TAs work a live queue, and results are
recorded in real time.

Each course has 40 competencies. A few rules keep the studio fair and moving:
students may request only a few per session (a cap), must keep progress on both
courses roughly balanced (the [balance rule](#the-balance-rule)), and a competency
a TA cannot get to is carried over rather than lost (see
[deferred competencies](#deferred-carried-over-competencies)).

## Quick start

**First-time setup** (clone, then from the repo root):

```
python3 -m venv venv              # create the virtualenv
source venv/bin/activate          # activate it (every new shell)
pip install -r requirements.txt   # install Flask
sqlite3 course-data.db < schema.sql   # build the database structure
sqlite3 course-data.db < seed.sql     # load sample students + competencies
```

**Run the app** (the day-to-day command):

```
source venv/bin/activate
flask --app app run --debug --port 8080
```

Open `http://127.0.0.1:8080/`. `--debug` gives auto-reload and full error pages.
Port 8080 avoids the macOS AirPlay conflict on 5000. The database is a file
(`course-data.db`) and persists between restarts; you only re-run the two
`sqlite3` commands to wipe and rebuild it (e.g. after a schema change).

**Dev logins.** There is no password in development (CAS replaces this later) —
on `/login`, type one of the seeded usernames:

| Type this | Signs in as |
|-----------|-------------|
| `dmason` | staff (lands on the evaluation queue) |
| `lfortune` | staff. Sign in as a *second* TA in a private window to watch queue claiming: a student claimed by `dmason` disappears from `lfortune`'s queue. |
| `600990517` | student Priya Singh |
| `500880917` | student Sarah Hassan |
| `500111111` | student Alice Chen |
| `500222222` | student Ben Okafor |
| `500333333` | student Chloe Diaz |

Sign several students up for the same competency to see the by-competency cohort
view do something interesting.

**Run the tests.** From the repo root with the venv active:

```
python -m pytest tests/
```

The suite (~90 tests) covers the queue and the two-TA claiming race, the balance
rule, deferred competencies, attendance, peer shout-outs, per-course enrollment,
and the auth guards.

## What it does

After signing in (`/login`), staff land on the evaluation queue, students on their
own progress page. The pages:

- **Home** (`/`) — the student roster (staff), a Mark and a View link per student.
- **Progress** (`/view/<student_number>`) — read-only competency status, grouped by
  course. A student sees only their own.
- **Marking** (`/mark/<student_number>`, staff only) — one tap per competency sets
  Achieved / Not passed / Not assessed and saves.
- **Evaluation queue** (`/queue`) — the live lab coordination:
  - **Students** sign up for the competencies they want evaluated (only ones they
    can attempt, from their enrolled courses, within the
    [session limits](#the-balance-rule)), enter a **seat** when they arrive (which
    is what puts them in front of staff), and **check in** for
    [attendance](#attendance). They can also
    [book ahead](#studio-sessions-and-advance-scheduling) for a future session.
  - **Staff** work the waiting students, longest-waiting first, grouped **by
    student** or **by competency** (toggle at the top). Claiming a card takes that
    student (or a whole competency cohort) and opens the screen to mark each one
    **Achieved / Not passed / Can't evaluate** (which
    [defers it](#deferred-carried-over-competencies)). Marking is one tap, with an
    **Undo**; a student can be **released** back to the queue.

The by-competency grouping is a **TA worklist, not a group session**: marking a
cohort back to back holds one consistent standard (and students cannot copy each
other). The subtler mechanics, two TAs never colliding on one student, and seats
gating who is visible, are next.

### Queue claiming

Two TAs must never walk over to the same student. Selecting a student *claims*
them: their requests flip to `claimed` by that TA and they vanish from every other
TA's queue.

The claim is a single conditional `UPDATE`, and the affected row count decides the
winner (`db.claim_student`):

```sql
update requests
   set status = 'claimed', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP
 where student_number = ?
   and (seat is not null and seat != ''
        and (status = 'waiting'
             or (status = 'claimed' and claimed_at < datetime('now', ?))));
```

`rowcount > 0` → the student is yours. `rowcount == 0` → another TA got there
first, because *their* write is what made the condition false for you. That is
**optimistic concurrency control**: there is no explicit lock, the `WHERE` clause
*is* the lock.

A `SELECT`-then-`UPDATE` would be broken here. Both TAs would read `'waiting'`,
both would pass the check, and both would write, with the second silently
overwriting the first. The check and the write have to be one statement so nothing
can interleave between them.

**Claiming takes the whole student**, not just one of their requests. A student can
only talk to one TA at a time, so handing the same student to two TAs (one per
competency) would move the collision out of the queue and into the room. The
visible cost: if Alice wants Recursion *and* Nested loops, and a TA takes the
Recursion cohort, Alice drops out of the Nested loops cohort until that TA is done
with her. Cohorts can look smaller than expected.

**Stale claims.** A TA who claims a student and then closes their laptop would
otherwise strand that student where no TA can see them. A claim older than
`claim_timeout_minutes` (a `settings` row, default 20) counts as available again.
This is evaluated at read time, in the same `db.AVAILABLE` predicate used to list
the queue and to guard the claim, so there is no sweeper job and the two can never
disagree about who is free.

**Undo** returns a request to `claimed` *by the same TA*, not to `waiting`. A
mis-tap while standing at the student's desk should not fling them back into the
global queue for someone else to pick up.

That `seat is not null` at the top of the predicate is the "is the student actually
here?" check: a student who has not taken a seat cannot be listed *or* claimed, so a
TA never walks over to an empty chair.

## Studio sessions and advance scheduling

The studio meets three times a week (Tuesday, Wednesday, Thursday). A sign-up is
for a specific **studio session**, not just "today": a student can book ahead, and
each request carries the `studio_date` it is for. The staff queue defaults to
today's live, claimable session; a TA can switch to a future day to see a read-only
**planning roster** of who has booked it. Studio days come from the weekly pattern
in `logic.py` (no term calendar yet).

## The balance rule

Each session, a student may sign up for at most a few competencies (the cap,
default **3**, a `settings` value Dave can change without touching code), and their
two courses must stay **within 1 of each other**: 2 of one course and 1 of the
other is fine, but 3 and 0 is not. This keeps students moving through both CPS109
and CPS213 rather than bingeing one. A sign-up that breaks the cap or the balance is
**rejected whole**, with a message explaining why. The rule is a pure function
(`logic.session_signup_ok`) checked against the session's per-course tally
(`db.session_course_counts`) in `queue_join`.

## Deferred, carried-over competencies

A TA who is not prepared to evaluate a competency taps **"Can't evaluate"** on it.
Rather than failing the student, the competency is *bumped*: it returns to the queue
tagged with the TA who bumped it (`bumped_by`). Three things follow:

- The by-student queue **flags a student that TA previously bumped**, so they can
  pick it back up once prepped, or steer clear.
- The bumped competency **waits for the student**: when they next take a seat it
  follows them to that session (`db.carry_bumped_forward`), so it is never stranded
  on a day they do not return.
- It **does not count against the student's cap or balance**, and the student sees
  it as "carried over", not failed.

## Attendance

Students check in each session ("I'm here today"), recorded in `attendance`
(`student_number`, `day`); taking a seat marks attendance too. Staff get an
attendance view (sessions attended per student) for the instructor's
miss-more-than-half rule. Check-ins only count on real class days.

## Peer shout-outs

A student can thank a classmate who helped them, from a dropdown on their own
progress page (`endorsements`). Staff see a received-count tally the instructor
folds into course remarks. One thank-you per classmate per day, enforced by the
table's primary key.

## Per-course enrollment

`enrollments` links a student to the courses they take, and students only see and
sign up for their enrolled courses' competencies. Most first-years take both
courses; a part-time student in one course sees only that one.

## Competency states

Each competency is in one of three states per student: **Not assessed** (no record
yet), **Achieved**, or **Not passed** (attempted, did not pass, then a cooldown
before retrying). Staff mark the third one "Not passed"; the student view shows it
as "Available to retry" with the time remaining.

```mermaid
stateDiagram-v2
    direction LR
    na: Not assessed (no row)
    ac: Achieved
    co: Not passed
    [*] --> na
    na --> ac
    na --> co
    ac --> na
    ac --> co
    co --> ac
    co --> na
```

This cooldown spaces out re-attempts. The rule (decided June 15): a "Not passed"
competency unlocks **two calendar days later at 8 AM Toronto time** (a Tuesday fail
unlocks Thursday 8 AM). Only the date of the attempt matters, not the hour. The
stored UTC timestamp is converted to `America/Toronto` first, so 8 AM is local and
the EST/EDT switch is handled automatically. The student view shows "Available to
retry &lt;day&gt; 8 AM", computed live from `date_recorded`. The queue enforces the
window: a cooling-off competency does not reappear in the student's sign-up list
until it passes. (A staff re-mark is not hard-blocked, but a student cannot
re-request early.)

## Architecture

Python / Flask backend, SQLite database. The code is split by responsibility so
each file has one reason to change:

| File | Responsibility |
|------|----------------|
| `app.py` | `create_app()` app factory: builds the app and registers the blueprints. |
| `blueprints/auth.py` | sign in / sign out (`/login`, `/logout`). |
| `blueprints/main.py` | roster home (`/`) and student progress (`/view/...`). |
| `blueprints/mark.py` | staff marking page (`/mark/...`) and per-tap save. |
| `blueprints/queue.py` | the evaluation queue (sign-up + staff marking). |
| `common.py` | helpers shared across blueprints: `current_user`, `userCas`, `page_header`. |
| `logic.py` | pure rules: competency states, the retry cooldown, studio sessions, and the sign-up balance rule. No Flask/DB/HTML. |
| `db.py` | all data access: the `db.cursor()` context manager and every query, claiming, attendance, enrollment, endorsements. |
| `myhtml.py` | HTML elements as Python classes; `str()` recurses to emit markup. |

- **Blueprints** group related routes into their own module, then get registered
  onto the app in `create_app()`. A route's endpoint name is prefixed by its
  blueprint, so links use `url_for('queue.queue')`, `url_for('main.index')`, etc.
- A request flows: **route** (a blueprint) → asks **`db.py`** for data and
  **`logic.py`** for rule answers → builds a page with **`myhtml.py`** → returns
  the HTML string.

```mermaid
flowchart LR
    Browser([Browser]) -->|HTTP request| Route[Blueprint route<br/>auth / main / mark / queue]
    Route -->|"current_user, page_header"| Common[common.py]
    Route -->|queries| DB[(db.py → SQLite)]
    Route -->|"rules: states, retry"| Logic[logic.py]
    Route -->|builds page| MyHTML[myhtml.py]
    MyHTML -->|HTML string| Browser
```
- **Production:** runs under Apache via `mod_wsgi`, with TMU CAS auth
  (`mod_auth_cas` sets a `Cas-User` header). In development the CAS user is
  hardcoded, so no Apache, CAS, or VPN is needed.

### Tap-to-save flow

```mermaid
flowchart LR
    A([Tap a button]) --> B[mark.js reads the data- attributes]
    B --> C[POST /save/student/competency/state]
    C --> D[Flask save_mark]
    D --> E[(SQLite: insert, replace, or delete)]
    E --> F[200 OK]
    F --> G[Button highlight updates in place]
```

The button changes color only after the save succeeds, so the screen always
matches the database.

## Data model

Schema and seed data live in `schema.sql` and `seed.sql`.

```mermaid
erDiagram
    students ||--o{ achievements : "has"
    competencies ||--o{ achievements : "has"
    students ||--o{ requests : "queues"
    competencies ||--o{ requests : "queued for"
    students ||--o{ enrollments : "enrolled in"
    students ||--o{ attendance : "present at"
    students ||--o{ endorsements : "gives / gets"
    students {
        TEXT student_number PK
        TEXT first_name
        TEXT last_name
    }
    competencies {
        INTEGER id PK
        TEXT name
        TEXT description
        TEXT course
    }
    achievements {
        TEXT student_number FK
        INTEGER competency_id FK
        TEXT status
        TEXT date_recorded
    }
    requests {
        INTEGER id PK
        TEXT student_number FK
        INTEGER competency_id FK
        TEXT seat
        TEXT requested_at
        TEXT status
        TEXT claimed_by
        TEXT claimed_at
        TEXT studio_date
        TEXT bumped_by
    }
    enrollments {
        TEXT student_number FK
        TEXT course
    }
    attendance {
        TEXT student_number FK
        TEXT day
    }
    endorsements {
        TEXT from_student FK
        TEXT to_student FK
        TEXT day
    }
    settings {
        TEXT key PK
        TEXT value
    }
```

A row in `achievements` exists only for a recorded event; `status` is
`'achieved'` or `'cooling_off'`, and "not assessed" is the *absence* of a row
(derived at read time). `date_recorded` is a full timestamp, so the cooldown is a
single elapsed-time comparison. The composite primary key is (`student_number`,
`competency_id`). Competencies carry a `course` (CPS109 or CPS213). `settings`
holds config such as admin usernames and the per-session request cap. The
`enrollments`, `attendance`, and `endorsements` tables are each covered in their
feature sections above.

`requests` is the evaluation queue: one row per competency a student asks to be
evaluated on. `status` flows `'waiting'` → `'claimed'` → `'done'`:

| status | meaning |
|--------|---------|
| `waiting` | nobody has taken this student yet; shows in every TA's queue |
| `claimed` | a TA has taken them and is walking over. `claimed_by` is that TA, `claimed_at` is when. Hidden from every other TA's queue, and treated as `waiting` again once older than `claim_timeout_minutes`. |
| `done` | evaluated. The result is written to `achievements` and the request flipped, in one step. |

See [Queue claiming](#queue-claiming) for how a claim is made race-safe.
