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
    description TEXT
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
-- competency today; status is 'waiting' until an evaluator handles it
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_number TEXT,
    competency_id INTEGER,
    seat TEXT,
    requested_at TEXT,
    status TEXT,
    FOREIGN KEY (student_number) REFERENCES students(student_number),
    FOREIGN KEY (competency_id) REFERENCES competencies(id)
);

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO settings VALUES('admins','dmason lfortune');
INSERT INTO settings VALUES('years','2026/27 2027/28 2028/29 2029/30');
