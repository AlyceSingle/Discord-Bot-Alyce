# Repository Guidelines

## Project Structure & Module Organization
`src/main.py` is the bot entrypoint and initializes environment loading, logging, and command sync. Core bot logic lives in `src/chat/`, with `cogs/` for Discord commands/events, `services/` for orchestration, `config/` for prompt and feature settings, and `features/` for isolated subsystems. Database models and migrations live in `src/database/` and `alembic/`. Operational scripts are in `scripts/`, including `deploy_to_single.ps1` and `publish_snapshot_to_github.ps1`. Tests live in `tests/`. Runtime data, logs, and large assets belong in `data/`, `logs/`, and `assets/` and should stay out of commits unless explicitly required.

## Build, Test, and Development Commands
Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the bot locally with `.env` loaded automatically:

```powershell
python -m src.main
pytest
```

For the full stack, use `docker compose up -d`, then apply migrations with `docker compose exec bot_app alembic upgrade head`. For ops workflows, use `powershell -File scripts/publish_snapshot_to_github.ps1` and `powershell -File scripts/deploy_to_single.ps1`.

## Coding Style & Naming Conventions
Use Python with 4-space indentation and follow the style already present in neighboring files. Prefer type hints on new service-layer code. Use `snake_case` for modules, functions, and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Keep feature-specific code under `src/chat/features/<feature_name>/`. No repo-wide formatter is enforced in CI; `black` and `ruff` are only referenced as optional Alembic hooks.

## Testing Guidelines
Tests use `pytest` and `pytest-asyncio`. Name files `tests/test_<area>.py`. Mark async tests with `@pytest.mark.asyncio`. Mock Discord, HTTP, and provider boundaries rather than hitting live services. If a test depends on a local database or seed file, make that dependency explicit and skip cleanly when absent. Add regression coverage for any changed cog, service, or migration path.

## Commit & Pull Request Guidelines
Recent commits follow concise Conventional Commit prefixes such as `fix:` and `feat:`. Keep commits scoped to one logical change and mention the affected subsystem. Pull requests should summarize behavior changes, config or migration impact, deployment risk, and include screenshots only when UI or web surfaces change.

## Security & Operations
Never commit `.env`, tokens, database dumps, or logs. Keep deployment changes lightweight: the target server is memory-constrained. Back up production data before changing migrations, prompts, or deploy scripts.
