# Contributing

The canonical guide is `CONTRIBUTING.md` in the repository root; this page
summarises the day-to-day commands. For an agent-oriented map of the codebase,
see `AGENTS.md`.

## Setup

Backend and TUI are managed with [`uv`](https://docs.astral.sh/uv/) (Python
3.14). The frontend uses npm via the dockerised CI image. Everything else runs
through Docker Compose.

```bash
cp .env.example .env   # fill in values
./dev.sh               # start the dev stack (hot-reload)
```

See [Dev Mode](getting-started/dev-mode.md) for details.

## Tests

```bash
./test.sh                       # backend tests (dockerised test DB)
./test.sh tui                   # TUI tests
./test.sh tests/test_charts.py  # a single backend test (args forwarded to pytest)
./test-web.sh                   # frontend: vitest + svelte-check + css lint + build
```

## Linting

```bash
./lint.sh           # ruff (Python) + svelte-check + css
./lint.sh python    # Python only
```

## Conventions

- **Commits** — Conventional Commits (`feat(scope):`, `fix(charts):`,
  `chore(ci):`).
- **Database** — never edit an applied migration; add a new
  `migrations/NNN_*.sql`. The schema docs and ER diagram regenerate from the live
  schema (`tbls`).
- **API docs** — don't hand-edit the [API Reference](reference/api.md); enrich the
  FastAPI routes (`summary=`, `description=`, `response_model=`, docstrings) and
  it regenerates.
- **ADRs** — record significant, hard-to-reverse decisions as an
  [ADR](architecture/decisions/index.md).

## Building the docs locally

```bash
uv run python scripts/docs/gen_openapi.py        # API schema
./scripts/docs/gen_schema.sh                     # DB schema (needs Docker)
uv run --group docs mkdocs serve                 # live preview at :8000
```
