# Portable AI providers and Ollama

Classification and intelligence summaries can independently use **Anthropic,
OpenAI, DeepSeek, Google Gemini or Ollama**. Existing saved choices without a
provider still mean Anthropic. Opening Settings does not change choices or run
inference. Saving affects future batches/jobs only, not existing results.

This feature is mock/integration-tested; no live cloud inference or real Ollama
inference was used during implementation. Review/test your selected model with a
small workload before relying on it in production. Provider/model discovery is not a capability or accuracy
guarantee: embedding/image/audio-only models may appear in some catalogues and
will fail rather than produce fake classification. No automatic provider failover.

## Cloud setup (all operating systems)

1. Copy `.env.example` to the server's private `.env`. Set only the keys you use:
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`.
   Keep `.env` out of Git. API keys never go into browser storage or model settings.
2. Recreate API and worker so both receive the same environment. Merely restarting
   a container does not load edited env-file values. Use your reviewed deployment
   process; don't redeploy production just to try this feature branch.
3. Open **Settings → Models**, choose a provider for each purpose, then explicitly
   **Refresh available models**. Refresh makes metadata requests, never inference.
4. Choose an actual discovered model, select supported effort (Auto only for the
   new adapters) and Save. Both choices are verified before the database is updated;
   a failure leaves the previous shared settings intact.

Optional server-controlled HTTPS API proxy bases are `OPENAI_BASE_URL` (including
`/v1`), `DEEPSEEK_BASE_URL`, `GEMINI_BASE_URL` (including `/v1beta`). No arbitrary URL
can be submitted from Settings. Cloud HTTP, embedded URL credentials, query strings,
fragments and redirect forwarding are rejected. Treat configured proxies as trusted:
they can receive API keys and article/requirement content. Do not point a cloud key
at an untrusted endpoint. TLS verification stays enabled.

Ollama optionally accepts `OLLAMA_API_KEY` as Bearer auth for a protected proxy.
Raw Ollama installations commonly have no auth; do not expose one publicly.

## Ollama topology: choose explicitly, not by operating-system guess

`OLLAMA_BASE_URL` is unset by default, so the app never assumes a machine-specific
address. It must be reachable from **both API and worker processes**.

| App installation | Ollama location | Example explicit base URL |
|---|---|---|
| Native Python app | Same machine, loopback listener | `http://127.0.0.1:11434` |
| Docker app | Ollama service on the same Docker network | `http://ollama:11434` |
| Docker Desktop on macOS/Windows | Host-native Ollama | `http://host.docker.internal:11434` |
| Docker Engine on Linux | Host-native Ollama via configured host gateway | `http://host.docker.internal:11434` with the optional host override |
| Native or Docker app | Protected remote Ollama server/proxy | `https://your-model-service.example` |

Container `localhost` points at that container, not the host or another service.
Docker Desktop usually supplies `host.docker.internal`; Linux Engine can use the
optional `compose.ollama-host.yml` mapping with a supported `host-gateway` Engine.
Rootless/remote Docker engines may need a different explicit routable address.

A host-native Ollama service bound only to loopback may not accept connections
from a container. Configure its listener deliberately and firewall it to trusted
app/container clients. Binding `OLLAMA_HOST=0.0.0.0:11434` exposes interfaces: do not
use that without firewall/private-network protection. Prefer authenticated TLS for
anything beyond a single trusted host. No app setting automatically changes your
Ollama listener or disables TLS checks.

### Optional same-network Docker service

`compose.ollama.yml` adds a CPU-portable Ollama container and separate model-cache
volume, without publishing an Ollama host port. Set `OLLAMA_IMAGE` to a reviewed
pinned tag or digest first. It does not select/download a model automatically.

```sh
# Deployment examples only; review before executing against any live installation.
docker compose -f docker-compose.yml -f compose.ollama.yml up -d
# Replace MODEL_ID with the actual Ollama model you selected and can run:
docker compose -f docker-compose.yml -f compose.ollama.yml exec ollama ollama pull MODEL_ID
```

Then Refresh installed models in Settings. Pulling model weights needs network,
disk and possibly licence acceptance; generation can be slow/memory-heavy. The app
never pulls weights or starts an Ollama daemon on your behalf.

CPU works as a baseline, not a latency guarantee. NVIDIA GPU use requires a supported
host driver/container toolkit and explicit device configuration. Native Ollama may
be preferable for Apple Silicon acceleration. Windows users must distinguish native
Windows, WSL and Docker networking. No GPU flags or host networking are enabled
universally. Local inference has compute/electricity costs even without cloud tokens.

## Structured output and limits

- Anthropic keeps its native SDK structured-output and existing model-specific
  server-side refusal-fallback behaviour. There is no new cross-provider fallback.
- OpenAI uses Chat Completions with strict JSON Schema for classification.
- DeepSeek uses JSON-object mode plus the schema in its instructions; **this is
  not native strict-schema enforcement**. Local validation remains mandatory.
- Gemini uses `generateContent`, JSON MIME type and `responseJsonSchema`.
- Ollama uses `/api/chat`, schema-valued `format`, non-streaming completed answers
  and `num_predict`. Discovery uses `/api/tags` and lists installed models.
- All classifier results are parsed and locally validated against the app schema
  before applying them. Refusal, empty output, truncation, malformed JSON and schema
  mismatch fail the article instead of marking it irrelevant. Failed articles need
  an explicit retry/reclassification after the configuration/model is corrected.
- Alternative-provider summaries are buffered non-streaming responses; the durable
  summary queue/row locks and bounded worker batching remain in place.
- Alternative adapters support Auto effort only for now. Discovery metadata does
  not advertise reasoning knobs that the adapter has not implemented.
- `ALTERNATIVE_MODEL_MAX_TOKENS` defaults to 8192; classification requests normally
  use 4000, summaries up to the alternative cap, further limited by advertised
  output limits where available. A model may have a smaller undocumented limit;
  lower the cap or choose another model if the provider rejects it.
- `LLM_REQUEST_TIMEOUT_SECONDS` defaults to 180 (max 600); discovery uses a
  15-second read timeout and connections a 5-second timeout. New adapters do not
  retry failed/ambiguous inference automatically. A timeout can still be billable.
- New selectable model IDs are limited to 64 characters so provider-qualified
  provenance fits the existing 80-character database column. Longer discovery
  names are not offered. No database schema/old result rows are rewritten.
  New non-Anthropic results record `provider:model`; old Claude references remain
  unchanged. This records the requested ID/alias, not a guarantee of immutable
  model weights behind a provider alias. The shared settings row also retains
  provider, exact model and metadata.

## Safety and release workflow

Normal `compose.development.yml` keeps every cloud key and Ollama URL empty, blocks
server egress and starts no worker by default. The guard checks the new variables
as well. **Do not combine Ollama overrides with that offline development file.**
A live local/cloud integration test needs a separate deliberately enabled private
configuration, explicit test records and an agreed cloud-token budget. Never copy
production credentials/articles into a public demo or commit them to Git.

The feature requires no database schema migration: model choices extend the existing
JSON preference row, and result provenance uses existing model fields. Code rollback
is safe while preferences remain Anthropic. **Before rolling back to old code after
selecting other providers, restore the previous Anthropic choices or reset the model
settings row via the new UI.** Old code otherwise interprets stored non-Claude IDs
as Anthropic model names. Existing completed results are not reprocessed.

Provider HTTP errors expose only safe status/configuration messages, not provider
bodies, key values or prompt content. Don't enable verbose HTTP/header logging in
a public deployment. Discovery/save show configuration/access, not guaranteed task
quality. Keep human validation and provider-specific cost monitoring.

## Official API contracts consulted

- OpenAI: https://platform.openai.com/docs/api-reference/chat/create
- OpenAI discovery: https://platform.openai.com/docs/api-reference/models/list
- DeepSeek: https://api-docs.deepseek.com/api/create-chat-completion
- DeepSeek discovery: https://api-docs.deepseek.com/api/list-models
- Gemini: https://ai.google.dev/api/generate-content and https://ai.google.dev/api/models
- Ollama: https://docs.ollama.com/api/chat and https://docs.ollama.com/api/tags

Provider APIs/capabilities change. Pin/review dependencies and test the actual
provider/model before enabling a high-volume workload. No real keys or inference are
required for the automated test suite.
