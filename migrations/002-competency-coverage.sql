-- Which competencies a harder one already proves (#80).
--
-- Dave's reason is time. 44 students times 80 competencies over 35 evaluation days is
-- about 100 evaluations a session, which is roughly 7 minutes each, and he expects
-- CPS213 to run slower than that. A student who demonstrates nested ifs has plainly
-- shown they understand simple ifs, so making them demonstrate both spends a slot on
-- something already proven.
--
-- DIRECT links only. If nested proves simple and simple proves comparison, record those
-- two rows and let the app follow the chain; do not also write nested -> comparison.
-- Every row is then one local judgement someone can actually make, and the map stays
-- small enough to review.
--
-- Empty until the competency list is ordered and scaffolded (#2). Deciding what proves
-- what is a judgement about the course, not about the app.
CREATE TABLE competency_covers (
    -- the harder competency, the one actually demonstrated
    competency_id INTEGER,
    -- the competency it proves, credited without being demonstrated
    covers_id INTEGER,
    PRIMARY KEY (competency_id, covers_id),
    FOREIGN KEY (competency_id) REFERENCES competencies(id),
    FOREIGN KEY (covers_id) REFERENCES competencies(id)
);
