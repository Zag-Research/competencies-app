# Migrations

## What this folder is for

When you're testing on your laptop and you change the database, you do this:

```
sqlite3 course-data.db < schema.sql
```

That throws the whole database away and builds a fresh empty one. Which is fine,
because the students in it are made up.

Once the app is running for real, that same command throws away 45 students' grades.
They can't be got back.

So this folder is the other way of changing the database: adding to the one that
already exists, instead of replacing it.

## What's in a file

One change, usually one line. `001-enrollment-withdrawal.sql` is:

```sql
alter table enrollments add column withdrawn_on TEXT;
```

That says: the enrollments table now has one extra column, called `withdrawn_on`.
Nothing is deleted. Everything already in the table stays exactly where it is.

## Why they're numbered

The database remembers a number, `schema_version`. Right now it's 1, because file
001 has been applied.

When you add `002`, `migrate.py` compares the folder against that number, sees the
database is behind, and runs only the new one. That's why they're separate files:
so it can tell what it has already done.

## Adding one

Three steps, and the third is the one people forget:

1. Write `migrations/002-what-it-does.sql` with your change.
2. Make the same change in `schema.sql`, so a brand new database is created with it
   already there.
3. Change `schema_version` in `schema.sql` to `2`.

Step 3 matters because a brand new database gets everything from `schema.sql`
immediately. If it still claimed version 1, `migrate.py` would try to apply file 002
to a database that already has it, and fail.

`tests/test_migrations.py` fails if you forget step 3, so you'll find out straight
away rather than on the server.

## Running them

```
./venv/bin/python migrate.py            # what would change, changes nothing
./venv/bin/python migrate.py --apply    # takes a dated backup, then does it
```

The backup is the recovery if something goes wrong halfway.
