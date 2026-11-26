# Repository workflow and future public release

## Current status

Intel Ingest is released under the MIT licence (see `LICENSE`). The public
repository is a history-free release snapshot: internal working notes
(`docs/internal/`) are excluded, and development history is kept separately.
Contributions must not include credentials, private data or real operational
intelligence requirements.

GitHub stores the source code and its history, not the running application or
its data. Creating or pushing this repository does not deploy the application,
stop Docker, or migrate the database.

## What belongs in Git

- Backend and frontend source code and automated tests.
- Docker configuration and dependency requirements.
- Documentation and the credential-free `.env.example` template.
- Geographic context with its attribution in `docs/globe-assets.md`.

Do not commit actual API keys, passwords, `.env` files, database dumps, article
exports, private dashboard/PIR configurations, logs or user data. `.gitignore`
excludes common local files; review staged changes before every commit. Ignoring
a file does not remove it from history if it was already committed.

`.dockerignore` also keeps local secrets, data and Git history out of the Docker
build context. Neither ignore file is a substitute for a secret review.

## Everyday workflow

Keep using the existing working directory for the current Docker deployment.

```bash
git status
# Make a focused change, then run the relevant tests.
git diff
# Stage only the files intended for this change.
git add path/to/changed-file
git diff --cached
git commit -m "Describe the change"
git push
```

For a new feature, start a branch with `git switch -c feature/short-description`.
Use separate Git worktrees for agents making concurrent edits. Integrate and test
changes before deploying; pushing to GitHub does not deploy them automatically.

Tests, in an isolated environment (no live database or API credentials required):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m unittest discover -s backend/tests -q
node --test frontend/tests/*.test.mjs
```

GitHub Actions runs both suites plus PostgreSQL concurrency/recovery tests against
an isolated PostgreSQL 16 service. To run those tests locally, set
`TEST_POSTGRES_URL` to a **disposable test database**, never the live database.
The tests create and drop their own uniquely named schema and terminate their own
test connection to simulate a database failure; the test user needs permission to
create schemas and terminate its own connections. Without that variable, the
PostgreSQL-specific tests are skipped; the SQLite/offline tests still run.

Interactive UI changes should also be checked in a real browser against the
built application. Use disposable test data and mocked external APIs while
developing; do not let parallel agents share the live database or ingestion worker.

## Configuration and database safety

A fresh clone does not include `.env`, articles or saved application settings.
Create local configuration from `.env.example` and supply credentials separately.
Review the template's model choices and ingestion settings before enabling work
that incurs API charges.

The existing PostgreSQL data remains in Docker's persistent `pgdata` volume.
Before a production update or migration, create a separate backup:

```bash
mkdir -p data/backups
docker compose exec -T db pg_dump -U intel -Fc intel \
  > "data/backups/intel-$(date +%Y%m%d-%H%M%S).dump"
```

Backups are intentionally ignored by Git. Store an additional protected copy
outside the project/machine according to your backup policy, and keep credentials
in a password manager or another secure location. A GitHub source-code copy is
not a database backup.

Do not run `docker compose down -v` or delete `pgdata`. If you later move the
working directory, identify and preserve the existing Compose project name and
volume before starting services from the new location. A different project name
can create an empty database volume that looks like lost data.

## Checklist before making the repository public

1. Explicitly approve the visibility change and select an open-source licence.
   Check ownership and any contributor/employer obligations first; do not assume
   that a private repository or publicly visible code grants reuse rights.
2. Scan the entire Git history for secrets and private information, not just the
   latest files. Rotate any exposed credentials and remediate history as needed.
3. Review documentation, tests, screenshots and fixtures for private operational
   details, customer names, real PIRs, personal information and article content.
4. Review third-party dependencies, licences, geographic assets and attribution.
   The existing map attribution is a starting point, not a complete legal audit.
5. Check NewsCatcher, model-provider and publisher terms. Publishing application
   code does not grant permission to redistribute fetched news or API credentials.
6. Test installation from a clean clone with a new database. Ensure it starts
   empty, has safe access controls and clearly explains possible API costs.
7. Add the chosen licence, contribution guidance, a security-reporting process
   and suitable CI checks. Update the README's repository-status section.
8. Review GitHub access, workflows, artifacts, releases, issues and any other
   material that would become visible. Only then change repository visibility.
