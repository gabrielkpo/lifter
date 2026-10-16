# Operations

How the hosted data is fed, backed up and checked. Everything here runs on the athlete's Mac:
the Garmin MCP server stays on `127.0.0.1` and is never exposed; only the database is hosted
(Neon, Frankfurt).

## Jobs

| Job (launchd) | When | What | Database role |
|---|---|---|---|
| `com.lifter.sync` | 07:30 and 21:00 | `lifter sync --days 3 --no-migrate`: last three days from Garmin into the raw layer; the schema is only checked | `lifter_sync` (writes the raw layer only) |
| `com.lifter.backup` | 13:00 | `pg_dump` of the whole database (custom format), kept 30 days, verified with `pg_restore --list` | `lifter_backup` (read-only) |
| `com.lifter.restore-check` | Sunday 13:30 | restores the latest backup into a throwaway local database and checks the core tables | none on the hosted side |

A job missed while the Mac sleeps runs at wake-up. Every failure raises a macOS notification;
logs are in `~/Library/Logs/lifter/`. Backups are in
`~/Library/Application Support/Lifter/backups/` (folder readable by this user only, disk
encrypted by FileVault).

## Set up

1. **Postgres 18 client tools**, the hosted database's version: `brew install postgresql@18`.
2. **The `lifter` command, apart from any working copy**, so a checkout on another branch never
   changes what runs: `uv tool install --force git+https://github.com/gabrielkpo/lifter@main`
   (again after each release to update it).
3. **Passwords of the job roles**, set once by the owner (roles come from `roles.sql`, created
   without password): `alter role lifter_sync password '…'` and the same for `lifter_backup`.
   Generate them, never reuse one.
4. **Environment files**, `chmod 600`, outside the repository:
   - `~/.config/lifter/sync.env`: `DATABASE_URL` (lifter_sync, direct endpoint, `sslmode=require`),
     `GARMIN_MCP_URL`, `GARMIN_MCP_TOKEN`, `SYNC_DELAY_SECONDS`;
   - `~/.config/lifter/backup.env`: `DATABASE_URL` (lifter_backup, direct endpoint).
5. **Jobs**: `ops/install.sh` (copies the scripts to `~/.local/share/lifter/ops` and loads the
   launchd agents); `ops/install.sh --uninstall` removes them.

Run a job by hand: `launchctl kickstart gui/$(id -u)/com.lifter.sync`.

## Schema changes

The jobs never change the schema. After a merge that adds a migration or changes `views.sql` or
`roles.sql`, the owner runs `lifter migrate` against the hosted database (owner URL in the
Mac's `.env`, never on Vercel); until then the sync stops with "schema out of date" and a
notification, and nothing is half-applied.

## Restore

`pg_restore --no-owner --no-privileges --dbname=<target> <dump>` into an empty database, then
`lifter migrate` with the target's owner to recreate roles and grants. Neon also keeps 6 hours
of history on the free plan (instant restore from its console).
