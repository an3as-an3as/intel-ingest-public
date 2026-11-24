# Isolated development and selective feature promotion

## Environment boundaries

| | Production | Development |
|---|---|---|
| Working directory | Existing production checkout | Separate Git worktree |
| Branch | `main` | Initially `development/environment` |
| Browser URL | http://localhost:8080 | http://localhost:8081 |
| Compose project | `intel-ingest` | `intel-ingest-dev` |
| Database/user | `intel` | `intel_dev` |
| Volume | `intel-ingest_pgdata` | `intel-ingest-dev-pgdata` |
| API credentials | Existing private `.env` | Forced empty in the offline stack |
| Server network | Existing production network | Separate internal Docker network |
| Ingestion worker | Existing production worker | Not started by default |

Do not combine the development Compose file with `docker-compose.yml`. It is a
standalone stack, not an override. The helper pins the project name, Compose file
and development environment file, then validates the resolved configuration before
running services. It refuses production ports, identities, shared volumes, live
provider keys and external networking for the application/database. A fixed Nginx
reverse proxy joins an additional edge network to publish the localhost UI; the
application itself remains on the internal-only network.

These controls protect against accidental cross-environment use. They are not a
security sandbox for hostile code or someone with Docker/host access. Browser-side
CDN dependencies still load normally from the browser; server-side provider access
is disabled by the internal network and empty credentials.

## Start and use development

From the development worktree:

```bash
./scripts/development.sh init
./scripts/development.sh check
./scripts/development.sh start
./scripts/development.sh status
```

Open http://localhost:8081. The header shows **DEVELOPMENT** and the browser title
starts with **[DEV]**. The database starts empty, without sample streams or
dashboards. Create test configuration deliberately in this environment. Nothing
is copied from production, including credentials and private PIRs.

`init` generates a development-only database password in ignored `.env.development`
with restrictive permissions; rerunning it preserves existing configuration.
Keep that file while keeping the database volume: changing its password does not
automatically change the password inside an existing PostgreSQL database.

The initial sandbox supports UI work, saving test configuration and query previews.
It does not fetch real articles, translate with a live model or classify with a
live model. Automated tests exercise provider-dependent behaviour with mocks.
A narrowly scoped live pilot requires separate approval and configuration; do not
copy the production `.env` or weaken the safety checks to bypass that decision.

Change `DEV_APP_PORT` only if 8081 is occupied. Port 8080 is forbidden by the guard.
Run the helper through Bash if executable permissions are unavailable:
`bash scripts/development.sh start`.

## Tests

```bash
./scripts/development.sh test
```

This builds the candidate application image, derives a backend test image from
that runtime with its installed dependency versions constrained, and runs Node
tests with read-only frontend/schema mounts. Backend tests use SQLite and mocked
providers, not either PostgreSQL database. Test dependencies are downloaded while
building/pulling images, before containers run on the internal network.

Alternatively, activate the project's Python test environment and run:

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -q
node --test frontend/tests/*.test.mjs
```

Check UI changes in a real browser as well. Do not infer successful integration
from unit tests alone. The prepared GitHub Actions workflow runs tests and checks
the development Compose boundaries on pull requests or manual invocation. It has
no deployment job, provider secrets or write permissions. It becomes available
only after the workflow has been committed/pushed; private-repository Actions
usage is subject to the account's included minutes and billing settings.

## Stop without deleting data

```bash
./scripts/development.sh stop
```

This stops only development and preserves its volume. The helper intentionally has
no reset or production-deployment command. Never run `docker compose down -v`
against production. Development article/configuration records must never be
promoted by copying its database over production.

## Feature workflow

1. Review the environment foundation separately. After approval, commit it and
   open a foundation pull request. No commits or pushes are required merely to
   evaluate the current local sandbox.
2. Once the foundation is accepted, create a small feature branch/worktree from
   the accepted baseline. Give each writing agent its own branch/worktree.
3. Define acceptance criteria, mock fixtures and dependencies before coding.
   Use the stages in `ingestion-rollout.md` rather than one combined rewrite.
4. Test each feature by itself, then the intended combination in development.
   Fix the query contract before parallel backend/frontend implementation.
5. Open one pull request per independently reviewable feature. Only merge accepted
   features into `main`; do not merge an entire experimental branch indiscriminately.
   Promote prerequisite changes first when features depend on one another.
6. New search behaviour should default off for existing streams. Use explicit,
   versioned per-stream configuration; test both baseline and experimental paths.
7. After explicit release approval, back up production's database and deploy only
   the approved code from the original production directory. Do not use an
   experimental worktree as production's Docker build context.
8. Record the tested image digest and dependency versions. Prefer promoting an
   immutable tested release image; if rebuilding for production, check dependency
   parity and rerun release tests. The existing requirements are not a complete
   transitive lockfile, so rebuilding source alone does not guarantee identical
   dependencies. Treat dependency upgrades as reviewable changes.
9. Smoke-test production, monitor collection quality/costs, and retain a rollback
   path. Turning off a feature does not undo a destructive database migration;
   prefer additive, backward-compatible migrations and test upgrade/rollback.

Pushing or merging code does not automatically deploy it. Production code, data
and running container IDs should remain unchanged while the sandbox is developed.
