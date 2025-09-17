# Repository Guidelines

## Project Structure & Module Organization
- `app.py` starts the Flask app and wires core services from `youspotter/`
- `youspotter/` holds domain modules such as `web.py`, `sync_service.py`, `spotify_client.py`, and downloader logic
- `tests/` mirrors package layout for pytest suites; add new tests beside related modules
- `static/` and `youspotter/static/` contain web assets, while Jinja templates live in `youspotter/templates/`
- `data/` stores stateful metadata and `downloads/` is the target library; keep secrets outside the repo

## Build, Test, and Development Commands
- `python app.py` boots the dev server at `http://localhost:5000`
- `docker-compose up -d` runs the container stack for environment parity
- `make test` executes pytest; `make lint` runs Ruff; `make format-check` enforces Black and isort
- Fresh setup: `python -m venv venv` then `pip install -r requirements.txt`

## Coding Style & Naming Conventions
- Python 3.12+, 4-space indentation, docstrings for public functions/helpers
- Use snake_case for functions/variables, PascalCase for classes, and lowercase module names
- Configuration constants belong in `youspotter/config.py`; avoid duplicating magic values
- Run Black and Ruff locally before committing; resolve or document any lint suppressions

## Testing Guidelines
- Place tests under `tests/` using `test_<module>.py` naming; mirror package structure
- Prefer pytest fixtures and fakes for Spotify/YouTube clients over live calls
- Cover new logic, especially error handling paths; add regression tests for bug fixes
- Use `pytest -k "keyword"` for targeted runs; full suite via `make test`

## Commit & Pull Request Guidelines
- Follow conventional commits (`feat:`, `fix:`, `chore:`) as seen in repository history
- PRs must state scope, validation steps (e.g., `make test`, `make lint`), and reference issues
- Attach screenshots or logs when altering UI flows or sync behavior
- Keep PRs focused; request review only after tests and linters pass

## Security & Configuration Tips
- Store OAuth credentials in environment variables or an untracked `.env`
- Scrub `youspotter.db*` and local tokens before sharing diagnostics
- Review dependency changes; pin versions in `requirements.txt` to avoid drift
