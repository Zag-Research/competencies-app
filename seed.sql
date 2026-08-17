-- students. More than two so the by-competency queue has a cohort worth looking
-- at: sign several of them up for the same competency to see them grouped.
INSERT INTO students VALUES('Priya', 'Singh', '600990517');
INSERT INTO students VALUES('Sarah', 'Hassan', '500880917');
INSERT INTO students VALUES('Alice', 'Chen', '500111111');
INSERT INTO students VALUES('Ben', 'Okafor', '500222222');
INSERT INTO students VALUES('Chloe', 'Diaz', '500333333');

-- enrollment. Most take both courses; Chloe is part-time in CPS109 only, so her
-- student view should show 40 competencies, not 80 (#11).
INSERT INTO enrollments VALUES('600990517', 'CPS109');
INSERT INTO enrollments VALUES('600990517', 'CPS213');
INSERT INTO enrollments VALUES('500880917', 'CPS109');
INSERT INTO enrollments VALUES('500880917', 'CPS213');
INSERT INTO enrollments VALUES('500111111', 'CPS109');
INSERT INTO enrollments VALUES('500111111', 'CPS213');
INSERT INTO enrollments VALUES('500222222', 'CPS109');
INSERT INTO enrollments VALUES('500222222', 'CPS213');
INSERT INTO enrollments VALUES('500333333', 'CPS109');

-- competencies: the official CPS109 (Python) and CPS213 (digital logic) lists,
-- 40 each, tagged by course. Each top-level competency is one row; its sub-points
-- from the source document become the description (the scope a TA evaluates).
-- Ids run 1-40 for CPS109, 41-80 for CPS213 (insertion order).

-- CPS109 (Python)
INSERT INTO competencies (name, description, course) VALUES ('Comprehension of algorithms, providing a set of instructions in a meaningful order', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses interactive shell for simple mathematical expressions and complex operations from the math library, using correct order of operations and syntax', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses variables with meaningful naming conventions to store values', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses print and input functions to communicate with the user', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the meaning of various syntax errors and runtime error messages and corrects the code', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Creates a single function to display text on the screen', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Creates a function with a meaningful return value', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Creates functions requiring 0 arguments, 1 argument, and many arguments. Understands the concept of default parameters and can produce an example', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the scope of local variables created within a function, differentiating from global variables. Uses and manipulates a global variable from inside a function', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses comparison operators and boolean algebra operators to produce boolean values', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the various forms of conditional structures', 'Uses an if statement for conditional commands; Uses an if-else structure for conditional commands', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Produces a conditional structure with multiple conditions', 'Uses an if-elif-else structure; Uses a nested control structure; Uses boolean algebra operators to combine conditions', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses string to represent text', 'Uses escape characters to produce formatted strings; Uses string indexing to access specific characters; Uses string slicing to extract a portion of a string; Uses string methods to modify strings; Uses concatenation to create new strings', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses type conversion to switch between data types', 'Strings to numeric data types (int, float, etc); Numeric data types to Strings; Numeric data type to another numeric data type; Uses ord() and chr() to convert between characters and ASCII values, and creates a new string using ASCII values', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a list to represent a group of data and retrieve values from it', 'Uses list indices to extract values from a list; Uses list slicing to extract a group of values from a list', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Performs operations on lists to modify the list itself', 'Uses list mutability to modify values within a list; Uses list concatenation to produce a new list; Uses list methods to perform operations on a list', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses tuples to group values together into a single entity, and unpacks tuples into separate variables', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a for loop to iterate over a sequence of numbers', 'Uses the range function to iterate over a special sequence of numbers', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a for loop to iterate over values in a sequence', 'Enhanced for loop, iterating over elements; Indexed for loop, iterating over indices of the elements', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Determines the largest value in a sequence using a for loop', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a while loop to iterate while a condition is true', 'Uses a while loop to replicate the functionality of a for loop; Understands the use of the break and continue keywords', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses list comprehension to produce a new list', 'Uses the range function to generate a sequence; Uses a conditional statement to create a more complex sequence', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a nested looping structure', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a set to hold unique values', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a dictionary to hold key:value pairs', 'Modifies key:value pairs in a dictionary', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Opens a file in read, write, or append mode', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Reads content from files and processes the data', 'read; readline; readlines', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Writes content to a file', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the concept of recursion', 'Implements a simple recursive function; Represents an iterative algorithm through recursion; Implements a recursive algorithm through iteration', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses recursion to process a list of values, and can trace through a recursive function call to show the change in inputs over time', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the structural difference between linear vs. branching recursion functions', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses an iterator to provide values in a for loop', 'Uses the next() function to extract the next value in the sequence from the iterator', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Produces a generator function, using the yield command to output values', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Uses a try/except statement to handle a simple runtime exception, and can implement a try/except block able to handle multiple exceptions separately', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the raise keyword and uses the raise command to create an exception', '', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands and implements the following search algorithms', 'Uses linear search to find an item within a list; Uses binary/bisection search to find an element within a list', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands and implements the following sort algorithms', 'Selection sort; Insertion sort; Bubble sort', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the purpose of time complexity', 'Can compare the time complexity of two searching algorithms; Can compare the time complexity of two sorting algorithms; Can produce a running time equation given an algorithm; Determines the time complexity from the running time equation', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Understands the concept of a Class', 'Understands the relationship between a Class and an Object; Creates a constructor method for a class', 'CPS109');
INSERT INTO competencies (name, description, course) VALUES ('Creates methods to interact with objects', 'Creates the __str__ method, used to output a string representation of the object; Creates accessor methods for a class; Creates mutator methods for a class', 'CPS109');

-- CPS213 (digital logic)
INSERT INTO competencies (name, description, course) VALUES ('Understands different numbering systems', 'Decimal; Binary; Hexadecimal; Octal; Other atypical bases, like base 5', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Converts between different numbering systems', 'Decimal to Binary; Decimal to Hexadecimal; Binary to Decimal; Binary to Hexadecimal; Hexadecimal to Binary; Hexadecimal to Decimal; Binary to Octal', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the different signed notations and which one is most commonly used in practice', 'Sign & Magnitude; 1''s Complement; 2''s Complement', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the range of values that can be represented with n digits for each numbering system', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Represents numbers in signed and unsigned notations', 'Converts positive and negative numbers between unsigned and signed notations; Converts signed numbers between the different signed notations; Sign extends a signed number to use the desired number of bits', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Performs binary unsigned addition', 'Detects overflow in unsigned addition', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Performs signed arithmetic operations', 'Binary signed addition; Binary signed subtraction; Understands and detects overflow for signed operations', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the functionality and truth table for the following logic gates, and can represent the gates as a boolean expression of two (or more) inputs', 'AND; OR; NOT; NOR; NAND; XOR; XNOR', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the functionality of a tri-state buffer', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Given a timing diagram, produces the correct output signal based on the inputs', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Performs boolean algebra simplifications to simplify an expression', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the basic identities', 'AND, OR Identity; Excluded Middle; Non-contradiction; Idempotence; Base; Involution (Double Negative); Commutative; Associative; Distributive; DeMorgan''s (large emphasis); Absorption', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands operator precedence', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Simplifies a given circuit using boolean simplification', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands how to represent binary terms as minterms or maxterms', 'Understands the relationship between minterms and maxterms: M0 = m0''', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Given a truth table, creates canonical expressions and their circuits', 'Creates an expression of the sum of minterms (Sum of Products), and a two-level circuit implementation; Creates an expression of the product of maxterms (Product of Sums), and a two-level circuit implementation', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Creates a truth table given the canonical form of a desired system', 'Sigma notation; Pi notation', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Uses DeMorgan''s Law to represent simple gates using only NAND Gates', 'NOT gate; OR gate', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Uses DeMorgan''s Law to represent simple gates using only NOR Gates', 'NOT gate; AND gate', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Uses DeMorgan''s Law to convert two-level circuits between all-NAND and all-NOR forms', 'Produces an all-NAND implementation of a two-level circuit from a Sum of Products expression; Produces an all-NOR implementation of a two-level circuit from a Product of Sums expression', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Transforms a truth table into a K-Map', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the rules of adjacency and groupings for a K-Map', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Creates SOP groupings of elements in a 2 input K-Map', 'Determines the boolean expressions for each grouping; Determines the overall boolean expression for the K-Map', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Creates POS groupings of elements in a 2 input K-Map', 'Determines the boolean expressions for each grouping; Determines the overall boolean expression for the K-Map', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Demonstrates the above competencies for 3 input K-Maps and 4 input K-Maps', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Produces a K-Map and boolean expression for a truth table with don''t care conditions (output for a given input combination is undefined)', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Understands the difference between a half-adder and a full-adder', 'Produces the truth table for each; Produces K-Map for each; Produces corresponding circuit for each; Represents a full-adder using half-adders and an XOR gate', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Produces a 2-bit adder circuit using half adders and full adders', 'Recognizes the relationship between carry out and carry in', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Produces a 4-bit adder circuit', '', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Produces a 4-bit adder/subtractor circuit with a control input to select the operation', 'Includes overflow detection functionality', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Produces a 2-input, 2-bit magnitude comparator', 'Creates the corresponding truth table; Creates the K-Map; Creates the circuit from the groupings', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Decoders', 'Understands and produces the truth table for a 2-to-4 decoder; Produces the resulting circuit; Adds low activated enable input to the decoder; Creates a 3-to-8 decoder using 2-to-4 decoders with enable; Adds an enable input to the 3-to-8 decoder', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Encoders', 'Understands and produces the truth table for a 4-to-2 encoder; Produces the resulting circuit; Priority Encoders: truth table and circuit for a 4-to-2 priority encoder', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Multiplexors', 'Truth table for a 2-channel MUX; Circuit for a 2-channel MUX; Function/truth table for a 4-channel MUX with two selector bits; Circuit for a 4-channel MUX; 2-channel, 2-bit MUX; Multiplexor with an enable input', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Arithmetic Logic Unit (ALU)', 'Understands the purpose and functionality of a general purpose ALU; Produces modular components contributing to the ALU; Uses multiplexors to select the behaviour of the circuit; Produces a complete ALU circuit', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Latches', 'SR latch, including the difference between a NOR and NAND SR Latch; Determines the output of a latch given its current state and inputs; Control input for an SR latch to avoid undefined behaviour; Control structure of a D Latch to avoid issues', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Flip Flops', 'Understands the synchronous nature of a Flip Flop; Trigger options (Level vs Edge Triggered, Positive vs Negative); Behaviour and next state for DFF, JKFF, TFF; Leader/follower (master/slave) FF using level-triggered FFs; Produces an excitation table from a function table; Uses an excitation table to determine required inputs for a change of states; Produces a timing diagram for a given input sequence', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('State Diagrams', 'Produces a state table from a circuit and determines next states for given inputs; Produces a state diagram from a completed state table', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Given a state diagram, produces a corresponding circuit diagram', 'Determines the FF inputs required to cause the transitions; Produces a circuit diagram implementing the state diagram; Produces alternate circuits using different FFs', 'CPS213');
INSERT INTO competencies (name, description, course) VALUES ('Register Circuit', 'Understands the functionality of a register and the purpose of its input signals; Produces a function table for a register; Produces a state diagram, state table, and circuit for a 1-bit register; Produces the above for a 4-bit parallel register', 'CPS213');

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
