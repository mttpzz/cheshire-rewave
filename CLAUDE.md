# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack overview

Self-hosted deployment of [Cheshire Cat AI](https://cheshirecat.ai/) customized for ReWave. Orchestrated via `compose.yml`:

- **cheshire-cat-core** — Cat core (`ghcr.io/cheshire-cat-ai/core:latest`) on host port `${CORE_PORT:-1865}`. Mounts local `plugins/`, `data/`, `doc/`, `static/`, `logs/`, so editing on host is live inside the container (`WATCHFILES_FORCE_POLLING=true` enables hot reload on Windows/OneDrive).
- **litellm** (`litellm_proxy`, port 4000) — LLM gateway. Config at `litellm/config.yaml` defines a single `cat-router` model with multiple backends (OpenAI, Anthropic, optionally Gemini). `routing_strategy: cost-based-routing` picks the cheapest available backend per call; on failure, retries up to `num_retries=2` and falls back to other deployments in the `cat-router` group (`allowed_fails=2`, `cooldown_time=30s`). Point the Cat admin UI at `http://litellm:4000` with `${LITELLM_MASTER_KEY}`.
- **db** — Postgres 16, stores LiteLLM spend logs / model metadata.
- **redis** — LiteLLM routing/model cache.
- **caddy** — Reverse proxy (`caddy:2-alpine`), terminates TLS on `:443` with internal CA. Hosts: `cat.rewave.local` → `cheshire-cat-core:80`, `litellm.rewave.local` → `litellm:4000`, `cat.files.local` → `host.docker.internal:8080` (external Filebrowser on Ubuntu host). Port 80 not published on Windows (often busy); `auto_https disable_redirects` set. Cat endpoints needing trailing slash (`/rabbithole`, `/plugins`, `/memory`, `/settings`, `/llm`, `/embedder`, `/auth`, `/users`) are rewritten to avoid 307s breaking POST/upload from admin UI. Trust roots in `caddy/caddy-root.crt_*` for client install.

All services share the `cat-network` bridge, so plugins/Cat reach LiteLLM at `http://litellm:4000`.

LiteLLM also wires Langfuse observability via optional `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` env.

## Common commands

```bash
docker compose up -d            # start full stack
docker compose logs -f cheshire-cat-core    # tail Cat logs
docker compose logs -f litellm              # tail LiteLLM logs
docker compose restart cheshire-cat-core    # reload after plugin struct changes
docker compose down             # stop stack (volumes preserved on host bind-mounts)
```

No build/lint/test harness — plugins are plain Python loaded by the Cat at runtime. Test changes by reloading the plugin from the Cat admin UI (`http://localhost:1865/admin`) or restarting `cheshire-cat-core`.

### Platform-specific config (Windows vs Ubuntu)

Some files toggle differently depending on the host OS. Always check both before bringing up the stack on a new machine:

- **`compose.yml` — caddy `ports`**:
  - Windows: leave `- "80:80"` commented (port 80 is often busy with IIS/system).
  - Ubuntu: uncomment `- "80:80"` so Caddy can bind 80 and serve HTTP→HTTPS auto-redirect normally.
- **`caddy/Caddyfile` — global block**:
  - Windows: keep `auto_https disable_redirects` active (no port 80 listener, so Caddy mustn't try to redirect from it).
  - Ubuntu: remove or comment `auto_https disable_redirects` so Caddy enables the standard automatic HTTP→HTTPS redirect on port 80.
- **`compose.yml` — `cheshire-cat-core.environment` `WATCHFILES_FORCE_POLLING=true`**: needed on Windows/OneDrive (filesystem events unreliable). On Linux drop it (inotify works) — slight CPU saving.

### Post-install fixes

After first `docker compose up -d` on a fresh host (especially Linux), run these to repair Cat container deps after the `file-manager` plugin pulls in `docling`. Plugin requirements alone don't cover ABI breaks against pre-installed Cat libs nor missing system shared objects:

```bash
# scikit-learn ABI break (numpy installed by docling shifts dtype size)
docker compose exec cheshire-cat-core pip install --force-reinstall --no-cache-dir scikit-learn

# openai client incompatible with httpx>=0.28 ('proxies' kwarg removed)
docker compose exec cheshire-cat-core pip install -U openai

# libGL needed by cv2 (docling_ibm_models tableformer); requires root
docker compose exec --user root cheshire-cat-core apt-get update
docker compose exec --user root cheshire-cat-core apt-get install -y libgl1 libglib2.0-0

docker compose restart cheshire-cat-core
```

Not persisted across image rebuilds — re-run after every `docker compose build` / pull. For permanent fix, fold into a custom `Dockerfile` extending `ghcr.io/cheshire-cat-ai/core:latest`.

## Plugins architecture (`plugins/*`)

Each plugin follows the Cat convention: `plugin.json` metadata + a Python module declaring `@tool`, `@hook`, `@form`, `@plugin settings_model`. User settings live in `settings.json` (edited via admin UI, also hand-editable here). Plugins share common patterns:

- **Per-user isolation**: `cat.user_id` scopes every filesystem/auth operation. Files go under `BASE_FOLDER_CAT/<user_id>/…` (container path, env `BASE_FOLDER_CAT=cat/doc`) and are served to the user via a link against `BASE_FOLDER_USER` (host-facing path). Path traversal guard: always wrap with `os.path.basename()` (see `plugins/file-manager/file-manager.py:get_user_path`).
- **LLM calls from plugins** use `cat.llm(prompt)` — routed through LiteLLM per the Cat's configured endpoint.
- **WebSocket UX**: `cat.send_ws_message("...")` pushes status/chat bubbles during long operations.
- **Scheduled jobs**: `cat.white_rabbit.schedule_interval_job(...)` (example: `email.py:schedule_email_classifier`).

### Plugin map

| Plugin | Purpose | Key entry points |
|---|---|---|
| `cat-rewave-settings` | Overrides core prompt + memory recall params (k/threshold for episodic/declarative/procedural). Also creates+announces per-user doc folder on first message. | `settings.py` (`MySettings`), `setup.py` (`agent_prompt_prefix`, `agent_prompt_suffix`, `before_cat_recalls_*_memories`, `before_cat_reads_message`, `get_folder_link`) |
| `email` | Microsoft Graph mail + calendar via MSAL device-flow auth, per-user token cache at `plugins/email/token/<user_id>/token_cache.bin`. | `email.py` (tools: `email_reader`, `email_sender`, `email_classifier`, `schedule_email_classifier`; form: `EmailReplyForm`), `calendar.py` (`get_upcoming_events`, `create_calendar_event`, `search_calendar_events`, `delete_calendar_event`), `auth.py` (`create_msal_app`, `get_access_token`) |
| `file-manager` | CRUD on user files (PDF via FPDF, DOCX via python-docx, TXT) + Docling-based RAG ingestion. | `file-manager.py` (`create_file`, `list_files`, `read_file`, `rename_file`, `delete_file`), `rag_helper.py` (`list_indexed_documents` tool, `DoclingMarkdownParser`, `rabbithole_instantiates_parsers` + `after_cat_bootstrap` hooks) |
| `vanna` | Text-to-SQL over a MySQL DB using Vanna AI with a Qdrant vector store. | `main.py` (`MyVanna`, `execute_sql_query`) |
| `web-search` | DuckDuckGo search fallback via `ddgs`. | `main.py` (`web_search`) |

### RAG ingestion (`file-manager/rag_helper.py`)

PDF/DOCX/DOC uploads hit `DoclingMarkdownParser` (registered via `rabbithole_instantiates_parsers`) instead of the Cat's default loaders — Docling converts → markdown before chunking, preserving tables/headings. `DocumentConverter` is heavy (loads ML models on first call), so:

- `_get_converter()` is a lazy singleton across all uploads.
- `after_cat_bootstrap` warms it at boot to avoid timing out the proxy on the first chat upload.

Per-user RAG isolation is enforced at recall time (see `cat-rewave-settings`): each declarative point's `metadata.user_id` filters listing/recall. The `list_indexed_documents` tool groups a user's points by source kind (file/url/text) using `metadata.source | filename | url` and reports chunk counts + last `indexed_at` (Europe/Rome).

### Email plugin auth flow

First use per user triggers MSAL device flow: `get_access_token` sends the `verification_uri` (clickable link, opens new tab) + `user_code` directly as a chat message via `cat.send_ws_message(..., msg_type='chat')`, then blocks on `acquire_token_by_device_flow` until the user authenticates, finally persists `token_cache.bin`. Subsequent calls reuse the cached token silently (with corrupt-cache fallback to a fresh device flow). User-to-mailbox mapping: `get_email_address(user_id)` → `<user_id>@rewave.it`, except `user_id == "admin"` → `<owner>@rewave.it`.

## Environment (`.env`)

Required by `compose.yml` / plugins:

- `CORE_PORT` (optional, default 1865)
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — passed to `litellm`
- `LITELLM_MASTER_KEY` — LiteLLM admin / client auth
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` — optional, for LiteLLM tracing
- `CLIENT_ID`, `CLIENT_SECRET`, `TENANT_ID` — MS Graph app registration (email plugin)
- `BASE_FOLDER_CAT` (container path, e.g. `cat/doc`), `BASE_FOLDER_USER` (host-facing URL/path used in chat links)
- `LOG_FOLDER`
- Vanna plugin also reads `QDRANT_URL`, `QDRANT_API_KEY`, `OPENAI_MODEL`, `DBHOST`, `DBNAME`, `DBUSER`, `DBPASSWORD`, `DBPORT`

`.env` is gitignored. If you rotate keys, do not commit them.

## Gotchas

- The `vanna/training` bind-mount in `compose.yml` uses an anonymous volume trick (`/app/cat/plugins/vanna/training` with no host side) to exclude that subfolder from the host mount — keep this line or training artifacts will clobber/pollute the host.
- `cat-rewave-settings/setup.py` overrides the core `agent_prompt_prefix`/`agent_prompt_suffix`. Live prompt text sits in `plugins/cat-rewave-settings/settings.json` (Italian, ReWave-specific), not in source — edit it via admin UI or that file.
- Plugin imports use `# type: ignore` on `cat.*` imports because the Cat SDK isn't installed in the local venv; they resolve only inside the container.
- `logs/` has a timezone convention (Europe/Rome) set per-plugin via `ZoneInfo`; keep it when adding new log timestamps.
- Cat & LiteLLM container ports are commented out in `compose.yml` — traffic goes through Caddy by hostname. To bypass Caddy for local dev, uncomment the `ports:` block (and add `cat.rewave.local`/`litellm.rewave.local` to your hosts file when using TLS).
- Docling models download on first conversion (~hundreds of MB); `after_cat_bootstrap` in `rag_helper.py` pre-loads them so first user upload doesn't hang the proxy.
- `compose.yml` boot order is gated by healthchecks: `db` (pg_isready) and `litellm` (HTTP `/health/liveliness`) must report healthy before `cheshire-cat-core` starts. Stop using `depends_on:` arrays here — `condition: service_healthy` is required, otherwise the Cat boots before LiteLLM is reachable and embedder/LLM calls fail.
- `file-manager/create_file` for `format=pdf` first tries `text.encode("cp1252")` (FPDF latin-1 limit). If text contains emoji/CJK/cyrillic it auto-falls back to DOCX with the same filename — the user gets `.docx` instead of the requested `.pdf`. Don't "fix" this by stripping non-latin chars; DOCX fallback is intentional.
- `file-manager/read_file` does NOT support `.doc` (legacy binary Word) — returns a "convert to .docx" message. RAG ingestion via Docling DOES accept `.doc` (registered in `DOCS_EXT`). Asymmetry is intentional: python-docx can't read `.doc`, Docling can.
- `EmailReplyForm.update()` is overridden to skip CatForm's default LLM-based field re-extraction. Reason: re-parsing chat history with the original email in context biases the LLM into swapping sender/recipient. Model is populated deterministically in `__init__`; `update()` only re-validates. Don't restore the default `update()`.
