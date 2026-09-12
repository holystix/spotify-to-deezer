# s2d

Migrates Spotify Liked Songs to Deezer Favourite Tracks so that Deezer's
"Recently added" sort reproduces Spotify's date-added order.

Deezer stamps a favourite with the time it was added, so the tool favourites
one track at a time, oldest like first, a few seconds apart. Any failure stops
the run; the next run resumes from the same row. Everything about your library
stays in the gitignored `data/` directory.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Google Chrome (the tool drives your own Chrome with a dedicated profile)
- A public Deezer profile, so favourites can be read back without an API key
- An export of your Liked Songs from [exportify.app](https://exportify.app),
  which includes ISRC codes. Exports from exportify.net also work but match
  less reliably.

## Setup

```sh
uv sync
uv run playwright install chrome   # only if Chrome is not already installed
cp .env.example .env               # set DEEZER_USER_ID and DEEZER_COUNTRY
uv run s2d login                   # log in to Deezer once in the window that opens
```

## Workflow

```sh
uv run s2d import data/export/liked.csv   # order by Added At, store in data/state.sqlite
uv run s2d resolve                        # ISRC lookup, then search
uv run s2d review                         # writes data/reports/review.csv
```

Decide each row in `review.csv` by adding a line to `data/overrides.csv`
with `source_uri`, a Deezer track id or URL or `SKIP`, and a note. Then run
`resolve` again. Tracks that map to the same Deezer track are added once.

For a track Deezer no longer carries, upload your own MP3 under Library →
MP3s in the web app and run:

```sh
uv run s2d uploads                        # writes data/reports/uploads.csv
```

Every upload is scored against the rows still awaiting a decision, and the
first three columns of each row are an `overrides.csv` line ready to paste.
An upload's Deezer id is negative and the public API cannot read it, so
`uploads` is the only thing that can supply its title, artist and duration:
run it before `resolve`. From there favourites, `time_add` order and `verify`
treat it as any other track.

Liked local files never appear in an Exportify export. Spotify's "Download
your data" archive lists them in `YourLibrary.json`, without dates:

```sh
uv run s2d reconcile path/to/YourLibrary.json   # writes data/reconcile.csv
```

Fill the `added_at` column from the Spotify app (Liked Songs sorted by Date
added): a date places the track last within that day, a full
`YYYY-MM-DDTHH:MM:SSZ` places it exactly, `SKIP` leaves it out. Re-run to see
where each lands between its neighbours, then `reconcile --apply` to insert
them and `resolve` to match them by search. Positions are renumbered, so do
this before the first `add`, or run `clear-favourites --yes` and start over.

```sh
uv run s2d add --dry-run   # show the next batch and anything blocking it
uv run s2d add             # favourite the batch, then verify
uv run s2d status
```

`add` refuses to start while any earlier row is still undecided, because a
track added out of turn cannot be moved. Do not use the Chrome window or
favourite anything by hand while a batch runs.

`verify` re-reads the favourites and checks that every recorded add is
present and in order. `verify --against fresh.csv` diffs a new export against
the imported one, to catch likes that changed during the migration.

`clear-favourites` empties the target account after writing a backup to
`data/reports/`.

## Configuration

`.env` (see `.env.example`):

| Variable | Meaning |
|---|---|
| `DEEZER_USER_ID` | numeric id of the target account, used to read favourites back |
| `DEEZER_COUNTRY` | two-letter country used for availability checks |
| `ADD_DELAY_MIN` / `ADD_DELAY_MAX` | seconds between adds |
| `BATCH_SIZE` | tracks per `add` run |
| `MATCH_THRESHOLD` | minimum search score to accept without review |
| `DURATION_TOLERANCE_MS` | duration difference still scored as a match |
| `HEADLESS` | run Chrome without a window |

## Development

```sh
uv sync                                   # installs the dev tools too
uv run pre-commit install                 # once; runs the checks below on commit
uv run ruff check && uv run ruff format --check
uv run basedpyright
uv run pytest --cov
```

Tests run against a temporary state file with synthetic data and never open
a browser or call Deezer.

## Limitations

- Tracks Spotify has withdrawn from its catalogue (greyed out in the app) are
  missing from every Exportify export. Only Spotify's data download lists
  them, without dates.
- Deezer offers no developer API registration, so writes go through the
  logged-in web app. If Deezer changes its web app the `add` step breaks.
- Only Spotify to Deezer is implemented. The source reader and the Deezer
  client are separate modules so another pair can be added.
