# App

A mobile-first web app, installable as a PWA (Next.js, `web/`), over a private HTTP API
(FastAPI, `src/lifter/api/`), read-only but for the conversation with the coach. The API reads the same analytics views as the CLI and
computes nothing of its own. Five tabs: **WOD** (the week, day by day, and each session planned
against done), **PRs** (best loads by kind and family, from the sets logged and the lift records declared to the coach), **Coach** (the conversations: the app opens on a new
one, kept while it stays open, the history panel on the left resumes any earlier one, named in the address `?c=`; what the
athlete asks is applied at once and shown under the reply with an undo; the coach's own ideas
come back as numbered suggestions, accepted with "ok pour N" in the conversation that showed
them),
**Planning** (three views: Cycles, the blocks counted in strength sessions; Weeks; Goals, a
table of targets, dates and next milestones) and **Health** (recovery
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
| `GET /goals`, `/bests` | Goals with milestones, best loads (logged sets and declared lift records) |
| `GET /history?exercise=` | The heaviest set per day of a movement, a declared record without a session (PR curves) |
| `GET /profile` | The athlete (age, never the birth date), declared health issues, active rules |
| `GET /status` | When the Mac's sync last stored or confirmed a Garmin payload (the app's freshness banner) |
| `GET /proposals?status=pending` | The agents' proposals |
| `GET /conversations?limit=50&before=` | The conversations with the coach, the most recently active first (id, title: the start of the first message, dates); `before`, the last id of a page, gives the next one |
| `GET /conversations/{id}?limit=50` | A conversation and its latest messages, oldest first: each athlete message with the changes it authorised, each reply with the suggestions it presented; 404 for an unknown id |
| `POST /conversations` `{text}` | A new conversation, opened by the athlete's first message, then the coach's answer to it (one turn, 1 to 8 model calls). Its id is drawn by the server. 502 if the model is unreachable, 503 if the database is or the coach is not configured; when the conversation was opened all the same, the error's `detail` names it (`conversation_id`) |
| `POST /conversations/{id}` `{text}` | The athlete's next message in a conversation, then the coach's answer: 404 for an unknown id, 409 if a newer message is waiting in it, 502 and 503 as above |
| `GET /conversation`, `POST /conversation` | The first conversation (`main`), for one release after 0.2.2, then removed |

Run locally, the API listens on `127.0.0.1` only, opens its database connection read-only and
requires a bearer token when `LIFTER_API_TOKEN` is set; only the app origins in
`LIFTER_APP_ORIGINS` may call it from a browser.

## Deployment

Three pieces, each behind Vercel's Deployment Protection (Vercel
Authentication on every deployment, production included):
- **App** (Vercel project `lifter`, root `web/`): the browser only talks to the app's own server,
  which reads the API (`web/app/api/[...path]/route.ts`, GET on the API's endpoints). The one
  write it forwards is a message to the coach (`POST /conversations`, `/conversations/{id}`), and only from the app's
  own pages: a request whose `Origin` is not the app's is refused (403). The API's address,
  token and protection bypass secret are server-side variables, never sent to the page.
- **API** (Vercel project `lifter-api`, entry point `api/index.py`): refuses to start without
  `LIFTER_API_TOKEN` when hosted, requires `Authorization: Bearer` on every request, answers
  only its own host names and allows no browser origin.
- **Database** (Neon Postgres, Frankfurt): the API connects with a role that can only read
  (`SELECT` grants, read-only transactions). The conversation uses two other roles: the
  athlete's message is stored as `lifter_chat` (`LIFTER_CHAT_DATABASE_URL`), which may open a
  conversation and write the athlete's words, nothing else; the coach answers as `lifter_coach`
  (`LIFTER_COACH_DATABASE_URL`), whose writes go through `lifter.operations` and are refused at
  commit without a trace. The model is Mistral (`MISTRAL_API_KEY`, `LIFTER_MODEL`), in
  `LIFTER_COACH_LANGUAGE`, within `LIFTER_RUN_TOKEN_BUDGET`; without these, the conversation
  answers 503. A turn may take tens of seconds: the API's function and the app's route may run
  60 s (`vercel.json`, `maxDuration`). The owner role, used for migrations, lives in the
  athlete's local `.env` and in the secrets of the GitHub `deploy` environment, never on
  Vercel.

**Production follows the versions, not the merges.** Vercel's Git deployments are off
(`vercel.json`, `web/vercel.json`): a merge or a pull request deploys nothing, not even a
preview. Merging release-please's pull request publishes a version (`vX.Y.Z`), and the Deploy
workflow then migrates the database, deploys the API, then the app, and checks the live API
(see [operations](operations.md#releases-and-deployment)).

Locally nothing changes: `uv run lifter-api` needs no token and the app's server reads it at
`http://127.0.0.1:8000` (`web/.env.example`). On Vercel, the app answers only its own host
names (`VERCEL_URL`, `VERCEL_BRANCH_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, plus
`LIFTER_WEB_HOSTS`), and the API the same (its Vercel host names, plus `LIFTER_API_HOSTS`,
comma-separated, for a domain of its own). Every API answer carries `Cache-Control: no-store`:
no browser or proxy keeps a copy of the athlete's data.
