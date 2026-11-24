# Add your own API keys or Ollama server

Keys belong on **your app server**, not in the browser, a GitHub issue, a screenshot
or this repository. Configure only the provider(s) you want to use. Classification
and summaries can use different providers. Existing installations keep their
saved choices until you change them in **Settings → Models**.

Consumer chat subscriptions are not the same as API access. Check the provider's
API billing, access restrictions and current prices; free access is not assumed.
Ollama needs installed model weights and suitable hardware, not a cloud API key
for a normal private local installation.

## 1. Obtain credentials

| Provider | Where to start | Variable in `.env` |
|---|---|---|
| Anthropic | [Anthropic Console](https://console.anthropic.com/) → API keys | `ANTHROPIC_API_KEY` |
| OpenAI | [OpenAI API keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` |
| DeepSeek | [DeepSeek API platform](https://platform.deepseek.com/) → API keys | `DEEPSEEK_API_KEY` |
| Google Gemini | [Google AI Studio API keys](https://aistudio.google.com/api-keys) | `GEMINI_API_KEY` |
| Ollama | Install/start Ollama and install a model; see [portable setup](model-providers.md#ollama-topology-choose-explicitly-not-by-operating-system-guess) | `OLLAMA_BASE_URL` |

Use the exact variable names above. This Gemini adapter uses the Gemini Developer
API/AI Studio key, not Vertex AI service-account credentials. The OpenAI adapter
uses the OpenAI API, not Azure-specific authentication/routes. Other services need
their own adapters or a deliberately compatible trusted proxy; not every API is
interchangeable.

Use separate restricted keys for this app where supported, set account spending
alerts/limits, and rotate a key if it is exposed. Never paste a real key into chat
or a shell command that will remain in terminal history.

## 2. Edit private server configuration

### First installation

In the repository folder, copy the credential-free template once:

```sh
cp .env.example .env
```

**Do not run that command over an existing `.env`.** For an existing installation,
edit its current `.env` in a local text editor instead. Keep its database password,
NewsCatcher settings and other working configuration intact. Changing
`POSTGRES_PASSWORD` does not automatically change a database user's password.

Fill in only the relevant entries; the values below are placeholders, not keys:

```dotenv
ANTHROPIC_API_KEY=
OPENAI_API_KEY=PASTE_YOUR_OWN_OPENAI_KEY_HERE
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
OLLAMA_BASE_URL=
OLLAMA_API_KEY=
```

Or set `GEMINI_API_KEY`, `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY` instead. You do not
need an Anthropic key when both purposes use other configured providers.
Do not add multiple conflicting definitions of the same variable. Values containing
special characters such as `$` or `#` should be quoted according to Docker Compose
`.env` syntax (single quotes prevent interpolation). API keys are normally a single
line; do not paste a whole JSON credential file into a key variable.

Protect the file: on macOS/Linux, `chmod 600 .env`; on Windows, restrict file access
to the account running the app. `.gitignore` excludes `.env`, but always inspect
`git status` before committing. Ignoring a file does not remove an old secret from
Git history. Back up configuration securely, separately from source code.

For a first database installation, also choose a strong `POSTGRES_PASSWORD` and set
`APP_PASSWORD`. APP_PASSWORD protects this app's UI/API, not the model provider's
account or a separately exposed Ollama server. Use HTTPS/VPN before sharing the
app beyond a trusted local environment.

### Local/remote Ollama instead of cloud keys

Configure the address reachable **from both the API and worker**:

| Topology | Example |
|---|---|
| Native app and Ollama on the same host | `OLLAMA_BASE_URL=http://127.0.0.1:11434` |
| App and Ollama in the same Docker network | `OLLAMA_BASE_URL=http://ollama:11434` |
| Docker Desktop app, host-native Ollama | `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| Linux Docker Engine app, host-native Ollama | Explicit reachable host address, or the optional host-gateway override |
| Protected remote server | `OLLAMA_BASE_URL=https://your-model-service.example` |

There is no universal machine-specific default. Container localhost is the container
itself. An Ollama service bound only to host loopback may not be accessible from a
container. See [listener, firewall, GPU and Compose instructions](model-providers.md).
Do not expose an unauthenticated Ollama port publicly. `OLLAMA_API_KEY` is optional
Bearer auth for a protected proxy, not a substitute for securing the raw service.
The app never downloads a model or starts an Ollama daemon automatically.

## 3. Apply environment changes

For a **first installation**, start from the repository folder:

```sh
docker compose up -d --build
```

For an **already installed current version**, adding/changing a key needs container
recreation, not a code rebuild or database replacement:

```sh
docker compose up -d --no-build --no-deps --force-recreate api worker
```

Use your **existing deployment directory, Compose project name, env-file and all
Compose override options**. If you use `-p`, `--env-file` or Ollama `-f` overrides,
repeat those options. Running under a new project name can create an empty volume
that looks like lost data. Don't use `down -v`, delete volumes or recreate the
database to apply a key. A plain `docker compose restart` does **not** reload edited
env-file values. Both API and worker must receive the same provider configuration.

For native Python, configure environment variables or a private `.env` in the
process's working directory, then restart both API and worker. A browser refresh
alone cannot change the server environment. The offline development Compose stack
intentionally forces keys/Ollama endpoints empty and blocks server egress; don't
weaken its safety guard or copy production keys into that test environment.

## 4. Select providers and models

1. Open the app → **Settings → Models**.
2. For **Article classification**, choose the configured provider and click
   **Refresh available models**.
3. Select an actual returned model appropriate for text classification. Discovery
   shows availability, **not** guaranteed schema support or intelligence quality.
4. Repeat for **Intelligence summaries**; this can be a different provider/model.
5. Select supported effort. Alternative adapters currently use **Auto** only.
6. Save. Both choices are verified before preferences are changed. Changing a key
   alone does not select that provider, and existing database preferences override
   environment defaults until you reset/change them here.

Refresh/Save perform model discovery/metadata checks, not inference. Article text
is not sent during discovery. Actual classification and report jobs can incur
cloud charges or consume local compute. Existing results are not regenerated by
saving; Pipeline → Reclassify and summary retry are explicit additional work.
Start with a small deliberate test before enabling a high-volume stream.

If configuring provider/model **environment defaults** instead of using Settings,
set `CLASSIFY_PROVIDER`/`SUMMARY_PROVIDER` and corresponding actual model IDs.
For non-Anthropic defaults, also set `CLASSIFY_EFFORT=auto` and/or
`SUMMARY_EFFORT=auto`. Avoid copying speculative or retired model IDs from an old
example; use provider discovery. Existing saved Claude choices remain Anthropic.

## Troubleshooting

- **Not configured:** check the correct server `.env`, exact variable name and
  container recreation for both API and worker. A key set only in a browser or a
  terminal's unrelated environment is not automatically in Compose's env-file.
- **Still showing Anthropic:** a saved preference is intentionally retained. Select
  the new provider for each purpose and Save; don't delete your data or dashboards.
- **401/403/429:** check API-key scope, model access, billing and rate limits. Never
  publish the key or raw provider error body. Requests are not automatically retried
  by the new adapters; a timeout can still have been billed.
- **No Ollama models:** ensure the app can reach the configured server and model
  weights are installed there. Installing a model on a different machine does not
  make it available on this server. Long model IDs above 64 characters are currently
  not offered; see the storage limitation in the provider guide.
- **Model discovered but inference fails:** choose a compatible text model, lower
  `ALTERNATIVE_MODEL_MAX_TOKENS` if needed, or correct its schema/endpoint support.
  Discovery is not an inference test. Invalid classifier JSON fails safely rather
  than being treated as irrelevant reporting.
- **Slow local model:** reduce classification concurrency/batch size and output cap,
  or adjust `LLM_REQUEST_TIMEOUT_SECONDS` (up to 600). Check hardware, model size and
  the Ollama listener/network. The app does not assume GPU support on every machine.

## Before publishing configuration or the repository

Share only `.env.example` with blank keys. Don't publish `.env`, private backups,
provider response caches, article exports, screenshots containing secrets or saved
operational dashboards. See [the public-release checklist](repository.md#checklist-before-making-the-repository-public).
Pushing code to GitHub is not permission to make the repository public or choose
an open-source licence; those are separate owner decisions.
