# Seneschal

Personal AI agent harness — self-hosted, Proxmox-based, security-first.

Samson is the single command principal. The agent runs as an unprivileged Linux user with deterministic enforcement (ingest, dispatcher, broker, egress) and model-backed orchestration (Qwen3-30B-A3B via llama.cpp on Tesla P40).

## Status

**Scaffold (v0.1.0)** — project structure, core contracts, and stub services aligned to the finalized build plan. Ready for incremental implementation following the build order in `docs/ARCHITECTURE.md`.

## Quick start (development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
cp config/ingest_allowlists.example.yaml config/ingest_allowlists.yaml
cp config/broker_policy.example.yaml config/broker_policy.yaml
mkdir -p data config

pytest tests/ eval/ -v
```

### Desktop client (build step 5)

1. Start llama.cpp with Qwen3-30B-A3B on `localhost:8080`
2. Start services:

```bash
seneschal-broker &
seneschal-dispatcher &
seneschal-shim
```

3. Point [Chatbox](https://chatboxai.app) or [Jan](https://jan.ai) at `http://127.0.0.1:8400/v1` with API key `dev-local-key`

## Project layout

```
src/seneschal/          Python package — all harness components
config/                 Allowlists, broker policy, egress (admin-only in prod)
agent_home_template/    Template for /home/agent filesystem convention
deploy/                 systemd units, nftables egress rules
eval/                   Regression eval set (plan §20)
docs/                   Architecture reference
tests/                  Unit tests
```

## CLI entry points

| Command | Component |
|---------|-----------|
| `seneschal-ingest` | Ingest layer smoke test |
| `seneschal-broker` | Capability broker daemon |
| `seneschal-dispatcher` | Subtask dispatcher daemon |
| `seneschal-orchestrator` | Orchestrator inbox poller |
| `seneschal-shim` | OpenAI-compatible desktop endpoint |
| `seneschal-trace <id>` | Query unified trace by correlation ID |

## Security model (summary)

- **Command vs content**: only authenticated principal messages are commands; everything else is untrusted data
- **Broker**: exposes actions not secrets; Twilio/OpenRouter creds never reach the agent user
- **Dispatcher**: persisted SQLite queue, budget enforcement, redaction before OpenRouter
- **Egress**: UID-based nftables default-drop + allowlisted proxy (deploy templates in `deploy/`)

## Hardware target

- 2× Tesla P40 (24 GB each), driver R580 + CUDA 12.x pinned
- Orchestrator: Qwen3-30B-A3B INT4 on GPU 1
- Voice stack (GPU 2): conversational model + faster-whisper + embedder

## License

MIT — personal project, not affiliated with any employer.
