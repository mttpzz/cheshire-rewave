# cheshire-rewave

Self-hosted deployment of [Cheshire Cat AI](https://cheshirecat.ai/) configured for Rewave, with a custom LLM routing layer and a set of internal plugins.

## Stack

- **Cheshire Cat core** — conversational AI framework (RAG, plugins, memory).
- **LiteLLM proxy** — routes model calls to OpenAI / Anthropic / Gemini (`cat-router`, cost-based routing with fallbacks), logs to **Langfuse**.
- **PostgreSQL** — LiteLLM spend/model logs DB.
- **Redis** — routing/cache layer for LiteLLM.
- **Caddy** — HTTPS reverse proxy with an internal CA (`tls internal`), exposing:
  - `cat.rewave.local` → Cheshire Cat admin UI / API
  - `litellm.rewave.local` → LiteLLM proxy
  - `cat.files.local` → Filebrowser (Ubuntu host only)

## Plugins

| Plugin | Purpose |
|---|---|
| `cat-rewave-settings` | Company system prompt + memory/retrieval tuning (episodic/declarative/procedural k & thresholds, chunking). |
| `email` | Microsoft 365 mail & calendar integration via MSAL device-flow login (`Mail.Read`, `Mail.ReadWrite`, `Calendars.Read`, `Calendars.ReadWrite`). |
| `file-manager` | File ingestion / RAG helper for uploaded documents. |
| `vanna` | Natural-language-to-SQL over a MySQL database, built on [Vanna](https://vanna.ai/). Ships with **demo credentials** (`root` / `password`) pointing at the `classicmodels` sample database (`host.docker.internal:3306`) — replace them via the plugin's own settings before pointing it at any real database. |
| `web-search` | Web search tool for the agent. |

## Setup

1. Copy `.env.example` (create one from the variables referenced in `compose.yml`: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `LITELLM_MASTER_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LITELLM_DB_PASSWORD`) to `.env`.
2. `docker compose up -d`.
3. Trust the Caddy internal CA on client machines to avoid browser TLS warnings (see `caddy/Caddyfile`).
4. Open `https://cat.rewave.local` to configure plugins from the admin UI.

## License

Source-available under the [PolyForm Strict License 1.0.0](LICENSE) — viewing and personal/noncommercial evaluation only. Any other use requires permission from Rewave Srl.
