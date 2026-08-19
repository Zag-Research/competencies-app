-- Mark a dropped enrollment instead of deleting it (#61).
--
-- Students can drop until Nov 20. Deleting the row is wrong twice over: the student's
-- results have to survive a drop that might be reversed, and competencies_for treats a
-- student with NO enrollment rows as taking everything, so removing rows would show a
-- dropped student the full list of both courses.
--
-- NULL means still enrolled. A date means they dropped on that date.
alter table enrollments add column withdrawn_on TEXT;
