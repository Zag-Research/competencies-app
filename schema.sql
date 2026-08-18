DROP TABLE IF EXISTS link_clicks;
DROP TABLE IF EXISTS links;
DROP TABLE IF EXISTS evaluations;
DROP TABLE IF EXISTS attendance;
DROP TABLE IF EXISTS endorsements;
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS requests;
DROP TABLE IF EXISTS achievements;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS competencies;
DROP TABLE IF EXISTS settings;

CREATE TABLE students (
    first_name TEXT,
    last_name TEXT,
    student_number TEXT PRIMARY KEY
);

CREATE TABLE competencies (
    name TEXT,
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT,
    -- which course this competency belongs to, e.g. 'CPS109' or 'CPS213'. The
    -- studio runs both at once, so every competency is tagged; per-course
    -- filtering in the student view is a separate step (#11).
    course TEXT
);

CREATE TABLE achievements (
    student_number TEXT,
    competency_id INTEGER,
    status TEXT,
    date_recorded TEXT,
    PRIMARY KEY (student_number, competency_id),
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (competency_id) REFERENCES competencies(id)
);

-- the evaluation queue: one row = a student asking to be evaluated on a
-- competency today.
--
-- status flows 'waiting' -> 'claimed' -> 'done':
--   waiting  no evaluator has taken this student yet; shows in the staff queue
--   claimed  a TA has taken the student and is walking over; hidden from every
--            other TA's queue. claimed_by is that TA, claimed_at is when.
--   done     evaluated, result written to achievements
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_number TEXT,
    competency_id INTEGER,
    seat TEXT,
    requested_at TEXT,
    status TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    -- which studio session this request is for, as an ISO date (#17). Students
    -- sign up ahead, so this is not always the day they pressed the button:
    -- requested_at is when they asked, studio_date is when they want it.
    studio_date TEXT,
    -- the TA who bumped this competency with "Can't evaluate" (#19/#24). Stays set
    -- after it goes back to 'waiting', so the queue can flag it for that TA to pick
    -- up later, and so it doesn't count against the student's cap. NULL = not bumped.
    bumped_by TEXT,
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (competency_id) REFERENCES competencies(id)
);

-- evaluations: one row per evaluation that actually took place (#48/#49). Appended,
-- never overwritten.
--
-- Deliberately separate from `achievements`, and the distinction is the whole point.
-- `achievements` holds the CURRENT STATE of a competency: one row per student and
-- competency, replaced when they retry. So a student who is marked "not passed" on
-- Tuesday and "achieved" on Thursday leaves exactly one row behind, Thursday's.
--
-- That is right for showing a student where they stand, and wrong for asking who is
-- carrying the evaluation load: the TA who did Tuesday's evaluation, the harder one
-- where they had to tell someone they were not ready, would vanish from the count.
-- Counting work needs the events, not the state.
--
-- A row is removed only by an undo, which exists for mis-taps: an evaluation that
-- was recorded by accident did not happen, and should not be counted as work.
CREATE TABLE evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_number TEXT,
    competency_id INTEGER,
    status TEXT,
    recorded_at TEXT,
    -- NOT NULL: every row here is created by a signed-in staff member marking
    -- something, so an evaluation with nobody attached is a bug, not a state the
    -- report should have to render.
    evaluated_by TEXT NOT NULL,
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (competency_id) REFERENCES competencies(id)
);

-- links: short things worth reading or watching, curated by the instructor (#51).
-- From the Aug 12 meeting: pieces about what goes wrong when software is written
-- without a human who actually understands it. Dave was openly unsure students would
-- read any of them, which is why link_clicks below exists.
--
-- Instructor-curated for now, his call. `why` is the one line that has to earn the
-- click, so it is stored rather than derived from the title.
CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    why TEXT,
    url TEXT,
    added_at TEXT
);

-- link_clicks: which students have opened which link. Dave: "Yes, track
-- click-throughs, probably per student so we can encourage students to stay engaged."
--
-- (student, link) primary key, so this records WHETHER a student opened something, not
-- how many times. Encouraging a student who has read nothing is the use; a click count
-- per student would invite reading it as enthusiasm, which it is not.
CREATE TABLE link_clicks (
    student_number TEXT,
    link_id INTEGER,
    clicked_at TEXT,
    PRIMARY KEY (student_number, link_id),
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (link_id) REFERENCES links(id)
);

-- peer helpfulness: one row = a student thanking a classmate who helped them.
-- The instructor folds the received counts into that classmate's course remarks,
-- one of the ways a student earns marks above the ~80% the competencies give.
--
-- The (from, to, day) primary key is the anti-gaming rule in the schema itself:
-- an 'insert or ignore' can only land one thank-you per classmate per day, so a
-- student cannot inflate someone by tapping repeatedly. A fresh day is a fresh
-- row, because they may genuinely have helped again.
CREATE TABLE endorsements (
    from_student TEXT,
    to_student TEXT,
    day TEXT,
    PRIMARY KEY (from_student, to_student, day),
    FOREIGN KEY (from_student) REFERENCES students(student_number),
    FOREIGN KEY (to_student) REFERENCES students(student_number)
);

-- attendance: one row = a student was present for one studio session (#attendance).
-- Deliberately separate from requests/seat: a student counts as present if they
-- showed up, whether or not they demonstrated a competency or ever took a seat.
-- The instructor's rule is a penalty for missing more than half the sessions, so
-- what matters is the raw "was here" signal, self-reported to save TA roll-call time.
--
-- (student, day) primary key: checking in twice the same session is a no-op, the
-- same insert-or-ignore trick used for endorsements.
CREATE TABLE attendance (
    student_number TEXT,
    day TEXT,
    PRIMARY KEY (student_number, day),
    FOREIGN KEY (student_number) REFERENCES students(student_number)
);

-- enrollment: one row = a student is taking one course (#11). The studio runs
-- CPS109 and CPS213 together, so a full-time student has two rows; a part-time
-- student may have only one, and should then see only that course's competencies.
--
-- A student with NO rows here is treated as enrolled in everything, so an
-- unenrolled or not-yet-loaded student is never shown a blank list.
CREATE TABLE enrollments (
    student_number TEXT,
    course TEXT,
    PRIMARY KEY (student_number, course),
    FOREIGN KEY (student_number) REFERENCES students(student_number)
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO settings VALUES('admins','dmason lfortune');
-- Which resolved hostnames count as studio lab machines (#46). CS systems' naming is
-- eng<room>-<machine>, e.g. eng201-01. Kept here rather than in code so a room change,
-- or relaxing the gate in an emergency mid-session, is a settings edit not a deploy.
INSERT INTO settings VALUES('lab_host_pattern','eng\d{3}-\d+');
INSERT INTO settings VALUES('years','2026/27 2027/28 2028/29 2029/30');
-- max competencies a student may request per studio session (#22). Dave: start
-- at 3 (students finish ~week 9), may bump to 4 later. A setting, so changing it
-- is one row update, not a code change.
INSERT INTO settings VALUES('daily_cap','3');
-- a claim this old is treated as abandoned, and the student returns to the queue.
-- Covers the TA who claims a student and then closes their laptop: without this,
-- that student is invisible to every TA forever.
INSERT INTO settings VALUES('claim_timeout_minutes','20');
