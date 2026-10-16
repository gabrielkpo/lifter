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

The sync needs the Garmin MCP server up on `127.0.0.1:8080` (a Docker container: Docker
Desktop must start at login), and the restore test needs the local Postgres server. A job
missed while the Mac sleeps runs at wake-up. Logs are in `~/Library/Logs/lifter/`, readable by
this user only (they can hold full tracebacks).

**Failures.** Every failure raises a macOS notification. macOS only shows it when notifications
are allowed for Script Editor (`osascript`) and no Focus mode hides them, so a failing sync can
go unseen: the app also shows a banner on every page when the Garmin data is more than 36 hours
old, and `lifter data-test --freshness` fails past 72 hours.

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

### Settings

Environment variables of the jobs; any of them can go in the optional
`~/.config/lifter/ops.env` (`chmod 600`, never a secret), read by every job before its own file.

| Variable | Default | What |
|---|---|---|
| `LIFTER_CONFIG_DIR` | `~/.config/lifter` | Folder of the job files (`ops.env`, `sync.env`, `backup.env`); set in the environment only |
| `LIFTER_LOG_DIR` | `~/Library/Logs/lifter` | Logs, folder readable by this user only |
| `LIFTER_BIN` | `~/.local/bin/lifter` | The `lifter` command installed by `uv tool install` |
| `PG_BIN` | Homebrew's `postgresql@18/bin` (Apple silicon, else Intel prefix) | `pg_dump`, `pg_restore`, `createdb`, `psql` |
| `LIFTER_BACKUP_DIR` | `~/Library/Application Support/Lifter/backups` | Dumps, read by the backup and the restore test |
| `LIFTER_BACKUP_KEEP_DAYS` | `30` | Dumps older than this are deleted |
| `LIFTER_SYNC_DAYS` | `3` | Days fetched again by each sync |

## Backups

One dump per day, verified with `pg_restore --list`, kept `LIFTER_BACKUP_KEEP_DAYS` days, in a
folder only this user can read; a dump left half-written by an interrupted run is deleted at the
next run. **The dumps are not encrypted themselves**: they hold the whole database, health data
included, and rely on FileVault. A copy that leaves the disk is a plain copy: exclude the folder
from Time Machine (`tmutil addexclusion` on it) unless the Time Machine disk is encrypted, and
never sync it to a cloud drive.

## Schema changes

The jobs never change the schema. After a merge that adds a migration, changes the dbt models
(`src/lifter/transform/`) or `roles.sql`, the owner runs `uv run lifter migrate` from a clone (dbt comes with the dev dependencies, or
the `transform` extra) against the hosted database (owner URL in the
Mac's `.env`, never on Vercel); until then the sync stops with "schema out of date" and a
notification, and nothing is half-applied.

## Data tests

`lifter data-test` runs the dbt data tests of the analytics layer (uniqueness, accepted values,
relationships, Lifter's own rules) against a database, read-only (the build hooks are skipped and the connection's options, a
read-only transaction included, reach dbt's own connection); `--freshness` also checks
that Garmin data arrived in the last 36 hours (warning) or 72 hours (error). Contracts are
checked when the layer is built.

## Restore

`pg_restore --no-owner --no-privileges --dbname=<target> <dump>` into an empty database, then
`lifter migrate` with the target's owner to recreate roles and grants. Neon also keeps 6 hours
of history on the free plan (instant restore from its console).
