"""Fail closed if resolved Compose configuration could cross environment boundaries.

Usage: docker compose ... config --format json | python3 scripts/check_development.py
Never prints configuration or credential values.
"""
import json
import sys
from urllib.parse import urlsplit


def validate_config(config):
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    require(config.get('name') == 'intel-ingest-dev', 'Unexpected Compose project name.')
    network = config.get('networks', {}).get('default', {})
    require(network.get('internal') is True and not network.get('external'),
            'Development must use an internal, non-external network.')
    require(set(config.get('networks', {})) == {'default', 'edge'}, 'Unexpected network definitions.')
    edge = config.get('networks', {}).get('edge', {})
    require(not edge.get('internal') and not edge.get('external'), 'Unexpected gateway edge network.')
    volumes = config.get('volumes', {})
    require(set(volumes) == {'pgdata'}, 'Unexpected top-level volume definitions.')
    volume = volumes.get('pgdata', {})
    require(volume.get('name') == 'intel-ingest-dev-pgdata' and not volume.get('external'),
            'Development database must use its own non-external volume.')
    services = config.get('services', {})
    require(set(services) == {'db', 'api', 'gateway', 'worker', 'backend-tests', 'frontend-tests'},
            'Expected only the six reviewed development services.')
    for name, service in services.items():
        require(not service.get('network_mode'), f'{name}: network_mode overrides are not allowed.')
        expected_networks = {'default', 'edge'} if name == 'gateway' else {'default'}
        require(set(service.get('networks', {})) == expected_networks, f'{name}: unexpected service networks.')
        require(not service.get('privileged'), f'{name}: privileged mode is not allowed.')
        if name != 'gateway':
            require(not service.get('ports'), f'{name}: host ports are not allowed.')
    db = services.get('db', {})
    db_env = db.get('environment', {})
    require(db_env.get('POSTGRES_USER') == 'intel_dev' and db_env.get('POSTGRES_DB') == 'intel_dev',
            'Database identity must be development-only.')
    db_mounts = db.get('volumes', [])
    require(len(db_mounts) == 1 and db_mounts[0].get('type') == 'volume'
            and db_mounts[0].get('source') == 'pgdata'
            and db_mounts[0].get('target') == '/var/lib/postgresql/data',
            'Unexpected database mount.')
    for name in ('api', 'worker'):
        service = services.get(name, {})
        env = service.get('environment', {})
        require(service.get('image') == 'intel-ingest-dev:local', f'{name}: unexpected application image.')
        require(not service.get('volumes') and not service.get('env_file'),
                f'{name}: application mounts or env files are not allowed.')
        require(env.get('APP_ENVIRONMENT') == 'development', f'{name}: missing development identity.')
        require(env.get('ANTHROPIC_API_KEY') == '' and env.get('NEWSCATCHER_API_KEY') == '',
                f'{name}: live API keys are not allowed in the offline environment.')
        require(all(not env.get(key) for key in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'GEMINI_API_KEY',
                                                'OLLAMA_API_KEY', 'OLLAMA_BASE_URL')),
                f'{name}: alternative provider credentials/endpoints are not allowed in the offline environment.')
        require(str(env.get('FETCH_ARTICLE_TEXT')).lower() == 'false', f'{name}: text fetching must be disabled.')
        require(str(env.get('KEYWORD_TRANSLATION_ALLOW_LIVE')).lower() == 'false', f'{name}: live translation must be disabled.')
        try:
            url = urlsplit(env.get('DATABASE_URL', ''))
            valid_url = (url.scheme == 'postgresql+psycopg' and url.hostname == 'db'
                         and url.username == 'intel_dev' and url.path == '/intel_dev')
        except ValueError:
            valid_url = False
        require(valid_url, f'{name}: unexpected database destination.')
    gateway = services.get('gateway', {})
    require(gateway.get('image') == 'nginx:1.28-alpine', 'Unexpected gateway image.')
    gateway_mounts = gateway.get('volumes', [])
    require(len(gateway_mounts) == 1 and gateway_mounts[0].get('type') == 'bind'
            and gateway_mounts[0].get('read_only') is True
            and gateway_mounts[0].get('target') == '/etc/nginx/conf.d/default.conf'
            and gateway_mounts[0].get('source', '').endswith('/deploy/development-nginx.conf'),
            'Unexpected gateway mount.')
    ports = gateway.get('ports', [])
    require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1'
            and ports[0].get('target') == 8080
            and str(ports[0].get('published')) not in ('', '0', '8080'),
            'Gateway must bind localhost on a non-production, explicit port.')
    require('worker' in services.get('worker', {}).get('profiles', []), 'Worker must require opt-in.')
    for name in ('backend-tests', 'frontend-tests'):
        require('tests' in services.get(name, {}).get('profiles', []), f'{name}: missing test profile.')
    return errors


def main():
    try:
        errors = validate_config(json.load(sys.stdin))
    except (ValueError, TypeError, AttributeError, KeyError):
        print('Invalid development configuration; refusing to continue.', file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f'BLOCKED: {error}', file=sys.stderr)
        return 1
    print('Development isolation checks passed: dedicated database/volume, localhost gateway, no API keys, internal application network.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
