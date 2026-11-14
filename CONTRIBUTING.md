# Contributing

Use Python 3.13 to match `.github/workflows/ci.yml`. The Docker runtime currently uses Python 3.12;
keep runtime changes compatible with both versions.

## Offline development setup

Create a virtual environment from the repository root:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux/macOS, or `.venv\Scripts\Activate.ps1`
in PowerShell. Install the runtime and test dependencies:

```sh
python -m pip install -r requirements-test.txt
```

Dependency installation requires package access unless dependencies are cached. For a fully
offline installation, prepare a wheelhouse on a connected machine with the same Python version
and platform, then copy it to the offline machine:

```sh
python -m pip download -r requirements-test.txt -d wheelhouse
python -m pip install --no-index --find-links=wheelhouse -r requirements-test.txt
```

Tests are offline and mock-only: no PostgreSQL, Redis, Discord token, API keys, Docker, or running
bot is needed. Leave `DONATE_ENCRYPTION_KEY` unset or empty, as CI does. Do not copy production
credentials into the development environment.

## Checks

Run the same checks as `.github/workflows/ci.yml` from the repository root:

```sh
python -m ruff check .
python -m mypy src/
python -m compileall -q src run_bot.py main.py
python -m pytest -v
```

For a quiet local test run without pytest's cache provider:

```sh
python -m pytest -q -p no:cacheprovider
```

Pull requests also run the separate secret-scan workflow. Check tracked files locally with
`python scripts/scan_secrets.py --git` before publishing a branch.

## Branches and pull requests

Branch from `main` with a neutral, descriptive name such as `fix/endpoint-authorization`,
`feat/voice-controls`, `perf/message-queue`, or `release/next`.
Follow the repository's conventional commit style: `fix: ...`, `feat: ...`, `perf: ...`,
`test: ...`, `docs: ...`, or `ci: ...`. Use a matching conventional title for the pull request.
Keep each change focused, add regression tests for fixes, and describe the behavior change
and validation results in the PR. Wait for CI and secret-scan checks before merging.
Use Git's configured identity for commits.

## Private security reports

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/azizu1012/Gemini-Bot-Discord/security/advisories/new)
using **Report a vulnerability**. Include affected versions, reproduction steps, impact, and
a minimal proof of concept with secrets removed. Avoid public issues or pull requests that
disclose an unpatched vulnerability.
