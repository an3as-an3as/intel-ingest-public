#!/usr/bin/env bash
# All commands are pinned to the isolated development project and Compose file.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env.development"
cd "$ROOT"

dc() {
  docker compose --project-name intel-ingest-dev --env-file "$ENV_FILE" \
    --file "$ROOT/compose.development.yml" "$@"
}

check() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo 'Run scripts/development.sh init first.' >&2
    exit 1
  fi
  dc --profile tests --profile worker config --format json | python3 "$ROOT/scripts/check_development.py"
}

case "${1:-help}" in
  init)
    umask 077
    python3 - "$ROOT" <<'PY'
import pathlib, secrets, sys
root = pathlib.Path(sys.argv[1])
path = root / '.env.development'
if path.exists() or path.is_symlink():
    print('Existing development configuration preserved.')
else:
    content = (root / '.env.development.example').read_text().replace(
        'development-placeholder-not-a-production-secret', secrets.token_urlsafe(32))
    with path.open('x') as f:
        f.write(content)
    print('Created private .env.development with a generated development-only database password.')
PY
    ;;
  check) check ;;
  start)
    check
    dc up -d --build gateway
    # Bind-mounted proxy configuration needs a reload after local edits.
    dc restart gateway
    port="$(dc config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["gateway"]["ports"][0]["published"])')"
    python3 - "$port" <<'PY'
import json, sys, time, urllib.request
url = 'http://127.0.0.1:' + sys.argv[1]
for attempt in range(30):
    try:
        with urllib.request.urlopen(url + '/api/meta', timeout=3) as response:
            meta = json.load(response)
        if meta.get('environment') != 'development' or meta.get('claude_configured') or meta.get('newscatcher_configured'):
            raise SystemExit('Unexpected environment/credentials at development URL; inspect configuration.')
        with urllib.request.urlopen(url, timeout=3) as response:
            html = response.read().decode()
        if 'id="environment-badge"' not in html:
            raise SystemExit('Development badge missing; inspect the built image.')
        print(f'Development ready: {url} (worker not started; live APIs disabled).')
        break
    except (OSError, ValueError):
        time.sleep(1)
else:
    raise SystemExit('Development readiness check failed; run scripts/development.sh logs.')
PY
    ;;
  stop)
    check
    dc stop
    echo 'Development stopped. Its database volume was preserved.'
    ;;
  status) check; dc ps ;;
  logs) check; dc logs --tail=100 api gateway ;;
  test)
    check
    dc build api
    dc run --rm --build --no-deps backend-tests
    dc run --rm --no-deps frontend-tests
    ;;
  help|-h|--help)
    echo 'Usage: scripts/development.sh {init|check|start|stop|status|logs|test}'
    echo 'Offline development only; no reset, production deployment or live-provider command.'
    ;;
  *) echo 'Unknown command. Run scripts/development.sh help.' >&2; exit 2 ;;
esac
