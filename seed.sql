-- SAMPLE DATA FOR LOCAL DEVELOPMENT. Never load this into production (#92).
--
-- Five students who do not exist, their enrolments, a couple of results, and two
-- sample competency coverage pairs. Loading it on a real deployment would put fake
-- students on the roster and credit real TAs with evaluations they never did, and
-- nothing would error.
--
-- The competencies themselves are NOT here any more. They are real course content and
-- live in competencies.sql, which production does load.
--
--   sqlite3 course-data.db < schema.sql
--   sqlite3 course-data.db < competencies.sql
--   sqlite3 course-data.db < seed.sql

INSERT INTO students VALUES('Priya', 'Singh', '600990517');
INSERT INTO students VALUES('Sarah', 'Hassan', '500880917');
INSERT INTO students VALUES('Alice', 'Chen', '500111111');
INSERT INTO students VALUES('Ben', 'Okafor', '500222222');
INSERT INTO students VALUES('Chloe', 'Diaz', '500333333');

-- enrollment. Most take both courses; Chloe is part-time in CPS109 only, so her
-- student view should show 40 competencies, not 80 (#11).
INSERT INTO enrollments (student_number, course) VALUES('600990517', 'CPS109');
INSERT INTO enrollments (student_number, course) VALUES('600990517', 'CPS213');
INSERT INTO enrollments (student_number, course) VALUES('500880917', 'CPS109');
INSERT INTO enrollments (student_number, course) VALUES('500880917', 'CPS213');
INSERT INTO enrollments (student_number, course) VALUES('500111111', 'CPS109');
INSERT INTO enrollments (student_number, course) VALUES('500111111', 'CPS213');
INSERT INTO enrollments (student_number, course) VALUES('500222222', 'CPS109');
INSERT INTO enrollments (student_number, course) VALUES('500222222', 'CPS213');
INSERT INTO enrollments (student_number, course) VALUES('500333333', 'CPS109');

-- competencies: the official CPS109 (Python) and CPS213 (digital logic) lists,
-- 40 each, tagged by course. Each top-level competency is one row; its sub-points
-- from the source document become the description (the scope a TA evaluates).
-- Ids run 1-40 for CPS109, 41-80 for CPS213 (insertion order).

-- CPS109 (Python)

-- CPS213 (digital logic)

-- achievements: the current state of a competency, one row per student. Columns are
-- listed explicitly so a future schema addition does not silently break seeding.
INSERT INTO achievements (student_number, competency_id, status, date_recorded)
  VALUES('600990517', 1, 'achieved', '2026-06-05 15:13');
INSERT INTO achievements (student_number, competency_id, status, date_recorded)
  VALUES('500880917', 2, 'achieved', '2026-06-05 15:13');

-- evaluations: the events behind those two results, plus the failed first attempt
-- that 600990517 made before passing. That third row is the case achievements alone
-- cannot show: two evaluations, one current state, and two different TAs who each
-- did a piece of work.
INSERT INTO evaluations (student_number, competency_id, status, recorded_at, evaluated_by)
  VALUES('600990517', 1, 'cooling_off', '2026-06-02 14:40', 'lfortune');
INSERT INTO evaluations (student_number, competency_id, status, recorded_at, evaluated_by)
  VALUES('600990517', 1, 'achieved', '2026-06-05 15:13', 'dmason');
INSERT INTO evaluations (student_number, competency_id, status, recorded_at, evaluated_by)
  VALUES('500880917', 2, 'achieved', '2026-06-05 15:13', 'lfortune');

-- requests (the evaluation queue) start empty: students create them at runtime by
-- signing up. Seeding fake ones made the staff queue show people who never signed
-- up, and a stale seat could mask a student's real seat in the grouped view.

-- competency coverage (#80): what demonstrating one competency already proves.
--
-- SAMPLE DATA, not the real map. seed.sql is local development only; production
-- installs schema.sql and loads a real roster, so nothing here reaches a student.
-- The actual map is a judgement about the course and waits on the list being ordered
-- and scaffolded (#2). These rows exist so the feature can be seen working.
--
-- This chain is Dave's own example from Aug 26, that a student who can write a
-- conditional with multiple conditions has plainly shown they understand simple ones:
--
--   12 Produces a conditional structure with multiple conditions
--     -> 11 Understands the various forms of conditional structures
--          -> 10 Uses comparison operators and boolean algebra operators
--
-- Two rows, not three. Direct links only; the app follows the chain, so marking 12
-- credits 11 and 10 both.
INSERT INTO competency_covers VALUES(12, 11);
INSERT INTO competency_covers VALUES(11, 10);
