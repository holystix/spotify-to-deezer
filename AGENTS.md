# s2d — agent notes

Migrates Spotify Liked Songs to Deezer Favourite Tracks in date-added order.
`README.md` has the operator workflow; `.agents/state/draft.md` (gitignored,
local only) is the design record and current status. Read it first when it
exists; update its "Where things stand" section when you change the plan.

## Working here

- Python 3.12 with `uv`. Run everything as `uv run s2d <command>`.
- Checks: `uv run ruff check`, `uv run ruff format --check`,
  `uv run basedpyright`, `uv run pytest`. `uv run pre-commit run --all-files`
  runs all four; `uv run pre-commit install` once makes them the commit hook.
- Tests use inline synthetic data only, never rows from `data/`, and must not
  reach the network or Playwright; an autouse fixture fails any that do.
  Browser and gw writes stay untested: exercise those against a copy of the
  state, `DATA_DIR=/tmp/x` with `data/state.sqlite` copied into it.
- The repository is public. Never commit anything from `data/`, `.env`, or
  `.agents/state/`, and keep account IDs, country and track lists out of
  README, commit messages and code.
- Deezer has no developer API for us. Reads use the public catalog endpoints
  in `deezer/catalog.py`; writes only ever run inside the logged-in page via
  `deezer/web.py`. Do not build a standalone client for the gw endpoints.
- The run is fail-fast by design: a track favourited out of order gets the
  wrong `time_add` and cannot be fixed without clearing. Stop on the first
  unexplained state, never retry an add automatically, never reorder.
- `position` is the migration order and `adds` references it. Anything that
  renumbers positions must refuse while `adds` has rows.
- Spotify is frozen until the final verify; do not suggest liking or
  unliking there.
- Commit messages: subject only unless the diff would mislead a reader.
