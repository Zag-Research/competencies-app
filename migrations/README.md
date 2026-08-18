# Migrations

One numbered SQL file per schema change, applied once, in order.

## Why this exists

`schema.sql` builds a database from nothing. That is the right tool for a fresh install
and the wrong one for a live database: running it drops every table, which in production
means destroying student results that cannot be regenerated.

So `schema.sql` stays the definition of a **new** database, and these files carry an
**existing** one forward. Both have to be updated for the same change: the migration so
live databases get it, `schema.sql` so fresh ones are born with it.

## Adding one

1. Write `migrations/NNN-short-description.sql`, taking the next number.
2. Make the same change in `schema.sql`.
3. Bump `schema_version` in `schema.sql` to `NNN`, so a fresh database knows it already
   has this and does not try to apply it again.

Step 3 is easy to forget, so `tests/test_migrations.py` fails if the number in
`schema.sql` does not match the highest file here.

## Applying them

```
./venv/bin/python migrate.py            # show what is pending
./venv/bin/python migrate.py --apply    # take a dated backup, then apply
```
