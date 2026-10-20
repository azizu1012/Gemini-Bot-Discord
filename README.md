<div align="center">

<img src="assets/azuris-banner.svg" alt="Azuris Discord AI Assistant" width="100%" />

<p>
  <a href="README.vi.md">Tiếng Việt</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="docs/endpoint_and_models.md">Endpoint Guide</a> ·
  <a href="docs/operations.md">Operations</a>
</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Discord.py-2.6.4-5865F2?logo=discord&logoColor=white" alt="discord.py" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/Redis-Streams-DC382D?logo=redis&logoColor=white" alt="Redis Streams" />
  <img src="https://github.com/azizu1012/Gemini-Bot-Discord/actions/workflows/ci.yml/badge.svg" alt="CI" />
  <img src="https://github.com/azizu1012/Gemini-Bot-Discord/actions/workflows/secret-scan.yml/badge.svg" alt="Secret scan" />
</p>

<p><strong>A reliable, endpoint-first AI assistant for Discord.</strong><br />
Multi-step reasoning, tool calling, long-term memory, multimodal input, voice-room utilities, and local infrastructure in one focused bot.</p>

</div>

## Overview

Azuris is an event-driven Discord AI assistant built around PostgreSQL, Redis Streams, and configurable LLM endpoints. It supports Google GenAI-compatible and OpenAI-compatible providers without hard-coding a provider-specific key pool into the application.

The project is designed for self-hosted deployments on Windows or Linux. PostgreSQL and Redis can run from the repository local runtime, so Docker is optional.

## Why Azuris

| Capability | What it provides |
| --- | --- |
| 🧠 Reasoning pipeline | Separate reasoning and final-synthesis stages with bounded retries and deadlines |
| 🧰 Tool calling | Web search, WeatherAPI.com weather, calculator, notes, role management, and image recognition |
| 🔌 Endpoint-first LLM | Configure SDK, URL, API key, and four model slots from Discord with /endpoint |
| 🖼️ Multimodal | Process image attachments and vision requests through the active endpoint |
| 🧾 Long-term memory | User-scoped notes, JSONB metadata, global-fact promotion, and file notes |
| 🔊 Voice rooms | Lock rooms, manage allowlists, move members, and apply room policies |
| 🛡️ Safety controls | Secret scanning, URL validation, user isolation, role checks, and sanitized errors |
| ⚡ Reliable runtime | Redis-backed event flow, per-user serialization, concurrency limits, and LLM deadlines |

## Architecture

Discord → Redis Streams → worker → LLM/tools → PostgreSQL → Redis → Discord

```mermaid
flowchart LR
    U[Discord users] --> G[Discord gateway<br/>bot_core.py]
    G --> I[(Redis Stream<br/>discord-incoming)]
    I --> W[Message worker<br/>message_handler.py]
    W --> P[Reasoning + synthesis<br/>GeminiPipeline]
    P --> T[Tools<br/>search · weather · notes · vision]
    P --> L[LLM Gateway]
    L --> E[(PostgreSQL<br/>endpoints · history · notes)]
    L --> R[GenAI or OpenAI-compatible<br/>endpoint]
    W --> O[(Redis Stream<br/>discord-outgoing)]
    O --> G
```

For the detailed module map and data flow, see [docs/architecture.md](docs/architecture.md).

## Quick Start

### Requirements

- Python 3.10 or newer
- Windows 10/11 or Linux
- A Discord bot token
- PostgreSQL 16 and Redis, either local or externally managed
- At least one configured LLM endpoint

### Windows

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt

powershell -ExecutionPolicy Bypass -File .\\install_services.ps1
Copy-Item .env.example .env
# Edit .env and fill in the required secrets.

powershell .\\run_bot.ps1 --preflight-only
powershell .\\run_bot.ps1 --server
```

Stop the bot and local services with:

```powershell
powershell .\\stop_bot.ps1
powershell .\\stop_infra.ps1
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chmod +x install_services.sh run_bot.sh stop_infra.sh
./install_services.sh
cp .env.example .env
# Edit .env and fill in the required secrets.

./run_bot.sh --preflight-only
./run_bot.sh --pm2 --server
```

## Configuration

Copy [.env.example](.env.example) to .env. Never commit .env or paste it into issues, pull requests, or chat.

Minimum configuration:

```env
DISCORD_TOKEN=your-discord-bot-token
ADMIN_IDS=your-discord-user-id
DATABASE_URL=postgresql://azuris:password@127.0.0.1:55432/azuris
REDIS_URL=redis://127.0.0.1:6379/0
DONATE_ENCRYPTION_KEY=your-fernet-key
WEATHER_API_KEY=your-weatherapi-key
```

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Endpoint API keys are encrypted before being stored in PostgreSQL. Plaintext endpoint-key storage is disabled by default; only enable ALLOW_PLAINTEXT_ENDPOINT_KEYS=true for an explicitly accepted local-development risk.

## LLM Endpoints

Azuris stores both provider configurations in PostgreSQL and activates one SDK at a time. Each endpoint has four model slots:

| Slot | Purpose | Fallback rule |
| --- | --- | --- |
| reasoning | Tool-aware reasoning loop | Falls back to final |
| final | User-facing synthesis | First available model |
| fallback | Same-provider retry model | Falls back to reasoning, then final |
| vision | Image understanding | Falls back to final |

Configure from Discord:

```text
/endpoint config
/endpoint view
/endpoint models
/endpoint test
/endpoint switch
```

For a local router_api:

```text
GenAI-compatible:  http://127.0.0.1:58100
OpenAI-compatible: http://127.0.0.1:58100/v1
```

Loopback is supported for local routers. Link-local, cloud-metadata, and unsafe private-network targets are blocked by default; see ALLOW_PRIVATE_ENDPOINT_HOSTS for an explicit trusted-LAN exception. Full details are in [docs/endpoint_and_models.md](docs/endpoint_and_models.md).

## Discord Commands

| Area | Commands |
| --- | --- |
| 🔧 Administration | /endpoint, /health_check, /moderator, /premium, /reset-all, /global-notes |
| 💬 Assistant | /ping, /reset-chat, /imagine, /donate |
| 🔊 Voice rooms | /lock, /unlock, /locklist, /allow, /allowremove, /allowlist, /move, /move_all, /set_room |

Permissions are enforced through static admin/moderator configuration and database-backed roles. Voice-room commands use owner/allowlist checks.

## Testing

```bash
python -m pytest -q
python -m compileall -q src scripts tests
```

The CI workflow runs compilation, PostgreSQL/Redis-backed tests, and the secret scan on every pull request. The repository current suite contains 171 passing tests.

## Security Notes

- Keep .env, database credentials, Discord tokens, API keys, and Fernet keys private.
- Rotate credentials immediately if the project directory or logs were shared.
- Use a dedicated Discord bot with only the permissions it needs.
- Keep DONATE_ENCRYPTION_KEY stable after endpoint keys have been stored; changing it requires re-encrypting stored keys.
- Review docs/incidents.md before changing runtime, Redis, or pipeline behavior.
- Run python scripts/scan_secrets.py --git before publishing a branch.

## Documentation

- [docs/architecture.md](docs/architecture.md) — system design and data flow
- [docs/configuration.md](docs/configuration.md) — environment variables and database schema
- [docs/endpoint_and_models.md](docs/endpoint_and_models.md) — endpoint and model-slot behavior
- [docs/operations.md](docs/operations.md) — installation, operations, logs, and troubleshooting
- [docs/deprecated.md](docs/deprecated.md) — removed and deprecated features
- [README.vi.md](README.vi.md) — Vietnamese documentation

## Contributing

1. Create a focused branch from main.
2. Add or update tests in tests/.
3. Run the local test and compile commands.
4. Open a pull request and wait for CI and secret-scan checks.
5. Merge only after all required checks pass.

## License

See [LICENSE](LICENSE).
