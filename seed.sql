-- students
INSERT INTO students VALUES('Priya', 'Singh', '600990517');
INSERT INTO students VALUES('Sarah', 'Hassan', '500880917');

-- competencies
INSERT INTO competencies (name, description) VALUES ('Nested loops', 'a programming structure where one loop is placed entirely inside the body of another loop');
INSERT INTO competencies (name, description) VALUES ('Recursion', 'occurs when a function or process calls itself to solve a smaller, self-similar piece of a larger problem');
INSERT INTO competencies (name, description) VALUES ('Pointers', 'a special programming variable that stores the memory address of another piece of data');

-- achievements (student_number, competency_id, status, date_recorded)
INSERT INTO achievements VALUES('600990517', 1, 'achieved', '2026-06-05 15:13');
INSERT INTO achievements VALUES('500880917', 2,'achieved', '2026-06-05 15:13');