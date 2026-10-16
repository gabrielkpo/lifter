# App

A mobile-first web app, installable as a PWA (Next.js, `web/`), over a private, read-only HTTP
API (FastAPI, `src/lifter/api/`). The API reads the same analytics views as the CLI and
computes nothing of its own. Five tabs: **WOD** (the week, day by day, and each session planned
against done), **PRs** (best loads by kind and family), **Coach** (chat, with the agents),
**Planning** (cycle, blocks counted in strength sessions, weeks, goals) and **Health** (recovery
read against the sessions of each day); the profile opens from the avatar.

```bash
uv run lifter-api                  # http://127.0.0.1:8000, interactive docs at /docs
cd web && npm ci && npm run dev    # http://localhost:3000
```

| Endpoint | Screen |
|---|---|
| `GET /weeks/current`, `/weeks`, `/weeks/{id}` | The week: review, intent, sessions with status and Garmin line |
| `GET /sessions/{id}` | A session: parts, planned and done, metcon target and result |
| `GET /calendar?start=&end=` | Sessions and activities between two days |
| `GET /program` | Cycle and blocks, strength sessions done against the block target |
| `GET /blocks/{id}` | A block: its weeks and each lift's top load, reps and RIR week by week |
| `GET /health?days=14` | Daily metrics, Garmin recovery values and alerts |
| `GET /goals`, `/bests` | Goals with milestones, best logged loads |
| `GET /history?exercise=` | The heaviest set per day of a movement (PR curves) |
| `GET /profile` | The athlete (age, never the birth date), declared health issues, active rules |
| `GET /status` | When Garmin data last arrived (the app's freshness banner) |
| `GET /proposals?status=pending` | The agents' proposals |

Run locally, the API listens on `127.0.0.1` only, opens its database connection read-only and
requires a bearer token when `LIFTER_API_TOKEN` is set; only the app origins in
`LIFTER_APP_ORIGINS` may call it from a browser.

## Deployment

Three pieces, each behind Vercel's Deployment Protection (Vercel
Authentication on every deployment, production included):
- **App** (Vercel project `lifter`, root `web/`): the browser only talks to the app's own server,
  which reads the API (`web/app/api/[...path]/route.ts`, GET on the API's endpoints only). The
  API's address, token and protection bypass secret are server-side variables, never sent to
  the page.
- **API** (Vercel project `lifter-api`, entry point `api/index.py`): refuses to start without
  `LIFTER_API_TOKEN` when hosted, requires `Authorization: Bearer` on every request, answers
  only its own host names and allows no browser origin.
- **Database** (Neon Postgres, Frankfurt): the API connects with a role that can only read
  (`SELECT` grants, read-only transactions). The owner role, used for migrations, lives in the
  athlete's local `.env` and in the secrets of the GitHub `production` environment, never on
  Vercel.

**Production follows the versions, not the merges.** Vercel's Git deployments are off
(`vercel.json`, `web/vercel.json`): a merge or a pull request deploys nothing, not even a
preview. Merging release-please's pull request publishes a version (`vX.Y.Z`), and the Deploy
workflow then migrates the database, deploys the API, then the app, and checks the live API
(see [operations](operations.md#releases-and-deployment)).

Locally nothing changes: `uv run lifter-api` needs no token and the app's server reads it at
`http://127.0.0.1:8000` (`web/.env.example`). On Vercel, the app answers only its own host
names (`VERCEL_URL`, `VERCEL_BRANCH_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, plus
`LIFTER_WEB_HOSTS`).
