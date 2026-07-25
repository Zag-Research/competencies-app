DROP TABLE IF EXISTS attendance;
DROP TABLE IF EXISTS endorsements;
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
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (competency_id) REFERENCES competencies(id)
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

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO settings VALUES('admins','dmason lfortune');
INSERT INTO settings VALUES('years','2026/27 2027/28 2028/29 2029/30');
-- max competencies a student may request per day (Dave to confirm exact number)
INSERT INTO settings VALUES('daily_cap','6');
-- a claim this old is treated as abandoned, and the student returns to the queue.
-- Covers the TA who claims a student and then closes their laptop: without this,
-- that student is invisible to every TA forever.
INSERT INTO settings VALUES('claim_timeout_minutes','20');
