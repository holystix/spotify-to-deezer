import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import urllib.parse

from . import browser, config, overrides, placements
from .deezer import catalog, favourites, verify
from .deezer.resolve import Resolver, apply_overrides, collapse_duplicates, match_uploads
from .deezer.web import GwError, GwSession
from .sources import exportify, spotify_export
from .state import State


def cmd_login(cfg: config.Config, _args) -> int:
    ok = browser.login(cfg.browser_profile, cfg.browser_channel)
    print("Logged in." if ok else "No Deezer session cookie found; log in again.")
    return 0 if ok else 1


def cmd_whoami(cfg: config.Config, _args) -> int:
    ok = browser.has_session(cfg.browser_profile, cfg.browser_channel)
    print("Session present." if ok else "Not logged in.")
    return 0 if ok else 1


def cmd_import(cfg: config.Config, args) -> int:
    path = _export_file(cfg, args.csv)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    export = exportify.read(path)
    tracks = export.tracks
    with State(cfg.state_path) as st:
        if st.get_meta("import_sha256") == digest:
            print(f"{path.name} is already imported ({len(tracks)} tracks).")
            return 0
        if st.count("adds"):
            print(f"Refusing to replace imported tracks: {st.count('adds')} adds are recorded.", file=sys.stderr)
            return 1
        if st.get_meta("reconcile_file"):
            print(f"Refusing to replace imported tracks: local files from {st.get_meta('reconcile_file')} "
                  "were merged in by reconcile and would be lost.", file=sys.stderr)
            return 1
        st.replace_tracks(tracks)
        st.set_meta("import_sha256", digest)
        st.set_meta("import_file", path.name)
        st.set_meta("import_at", datetime.now().isoformat(timespec="seconds"))

    tied = sum(n for n in Counter(t.added_at for t in tracks).values() if n > 1)
    print(f"Imported {len(tracks)} tracks from {path.name} ({export.variant}).")
    print(f"  oldest {tracks[0].added_at}, newest {tracks[-1].added_at}")
    print(f"  rows in same-second ties: {tied}, local files: {sum(t.is_local for t in tracks)}, "
          f"without Added At: {sum(t.added_at is None for t in tracks)}")
    if export.has_isrc:
        print(f"  without ISRC: {sum(t.isrc is None for t in tracks)}")
    else:
        print("  no ISRC column; resolution will rely on search. exportify.app exports include ISRC.")
    return 0


def _export_file(cfg: config.Config, arg: str | None) -> Path:
    if arg:
        return Path(arg)
    files = sorted(cfg.export_dir.glob("*.csv"))
    if len(files) != 1:
        raise SystemExit(f"Expected one CSV in {cfg.export_dir}, found {len(files)}. Pass the path explicitly.")
    return files[0]


def cmd_resolve(cfg: config.Config, args) -> int:
    with State(cfg.state_path) as st:
        if not st.count("tracks"):
            print("Nothing imported.")
            return 1
        resolver = Resolver(st, cfg.deezer_country, cfg.match_threshold, cfg.duration_tolerance_ms)
        applied = apply_overrides(st, resolver, cfg.overrides_path)
        pending = st.pending_tracks(retry=args.retry)[:args.limit or None]
        print(f"{applied} overrides applied; resolving {len(pending)} tracks.")
        for i, t in enumerate(pending, 1):
            res = resolver.resolve(t)
            st.upsert_resolution(res)
            if res.status != "matched":
                print(f"  [{t.position}] {res.status}: {_label(t)} | {res.note}")
                if res.candidate:
                    print(f"        suggestion: {res.candidate['artist']} - {res.candidate['title']} "
                          f"({res.candidate['duration']}s) {res.candidate['link']}")
            if i % 100 == 0:
                print(f"  {i}/{len(pending)}")
        dups = collapse_duplicates(st)
        if dups:
            print(f"{dups} duplicate rows re-flagged.")
        _print_counts(st)
    return 0


def cmd_review(cfg: config.Config, _args) -> int:
    with State(cfg.state_path) as st:
        rows = st.resolved(("unmatched", "needs-review"))
        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / "review.csv"
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["position", "added_at", "artists", "title", "duration_s", "isrc", "status", "note",
                        "suggestion_id", "suggestion_artist", "suggestion_title", "suggestion_duration_s",
                        "suggestion_link", "search_link", "source_uri"])
            for t, r in rows:
                c = r.candidate or {}
                q = urllib.parse.quote(f"{t.artists[0] if t.artists else ''} {t.title}")
                w.writerow([t.position, t.added_at, "; ".join(t.artists), t.title,
                            round(t.duration_ms / 1000) if t.duration_ms else "", t.isrc, r.status, r.note,
                            c.get("id", ""), c.get("artist", ""), c.get("title", ""), c.get("duration", ""),
                            c.get("link", ""), f"https://www.deezer.com/search/{q}", t.source_uri])
        overrides.ensure(cfg.overrides_path)
        print(f"{len(rows)} rows written to {out}. Record decisions in {cfg.overrides_path} and re-run resolve.")
    return 0


def cmd_reconcile(cfg: config.Config, args) -> int:
    path = Path(args.library)
    items = spotify_export.read(path)
    uris = {i.uri for i in items}
    with State(cfg.state_path) as st:
        known = {t.source_uri: t for t in st.tracks()}
        missing = [i for i in items if i.uri not in known]
        gone = [t for u, t in known.items() if u not in uris]
        print(f"{path.name}: {len(items)} liked tracks, {len(missing)} not imported "
              f"({sum(i.is_local for i in missing)} local files), {len(gone)} imported but no longer liked.")
        for t in gone:
            print(f"  - [{t.position}] {_label(t)}")
        rows = placements.sync(cfg.placements_path, missing)
        if not rows:
            print("Nothing to reconcile.")
            return 0
        pending = [p for p in rows if p.added_at is None and not p.skip]
        if pending:
            print(f"{len(pending)} of {len(rows)} rows in {cfg.placements_path} need an added_at: "
                  "YYYY-MM-DD (sorts last within that day), a full YYYY-MM-DDTHH:MM:SSZ, or SKIP.")
            for p in pending:
                print(f"  {_label(p.item)}")
            return 1
        placed = [p for p in rows if not p.skip]
        if not placed:
            print(f"All {len(rows)} remaining rows are SKIP.")
            return 0
        merged, inserted = placements.merge(list(known.values()), placed)
        print(f"{len(placed)} tracks to insert, {len(rows) - len(placed)} skipped:")
        for t in inserted:
            older = merged[t.position - 1] if t.position else None
            newer = merged[t.position + 1] if t.position + 1 < len(merged) else None
            print(f"  [{t.position}] {t.added_at} {_label(t)}")
            print(f"        after  {older.added_at if older else '-'} {_label(older) if older else 'start of list'}")
            print(f"        before {newer.added_at if newer else '-'} {_label(newer) if newer else 'end of list'}")
        if not args.apply:
            print("Re-run with --apply to insert them and renumber positions.")
            return 0
        if st.count("adds"):
            print(f"Refusing: {st.count('adds')} adds are recorded and would shift. "
                  "Run clear-favourites --yes first; add then starts over from position 0.", file=sys.stderr)
            return 1
        st.replace_tracks(merged)
        st.set_meta("reconcile_file", path.name)
        st.set_meta("reconcile_at", datetime.now().isoformat(timespec="seconds"))
        st.reset_duplicates()
        collapse_duplicates(st)
        placements.sync(cfg.placements_path, [p.item for p in rows if p.skip])
        print(f"Inserted {len(inserted)} tracks; {len(merged)} positions renumbered. Run resolve.")
    return 0


def cmd_uploads(cfg: config.Config, _args) -> int:
    with State(cfg.state_path) as st:
        with browser.persistent_context(cfg.browser_profile, headless=cfg.headless, channel=cfg.browser_channel) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.deezer.com/en/")
            browser.wait_security_check(page)
            gw = GwSession(page)
            if cfg.deezer_user_id and gw.user_id != cfg.deezer_user_id:
                print(f"Logged-in user {gw.user_id} differs from DEEZER_USER_ID {cfg.deezer_user_id}.", file=sys.stderr)
                return 2
            uploads = gw.personal_songs()
        for obj in uploads:
            st.cache_track(obj)
        rows = match_uploads(st, uploads, cfg.duration_tolerance_ms)

        cfg.reports_dir.mkdir(parents=True, exist_ok=True)
        out = cfg.reports_dir / "uploads.csv"
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([*overrides.HEADER, "score", "position", "upload_artist", "upload_title", "upload_album",
                        "upload_duration_s", "liked_artists", "liked_title", "liked_duration_s", "status"])
            for obj, pair, score in rows:
                t, r = pair or (None, None)
                confident = t is not None and score >= cfg.match_threshold
                w.writerow([t.source_uri if confident else "", obj["id"],
                            f"upload of {obj['artist']['name']} - {obj['title']}" if confident else "",
                            score, t.position if t else "", obj["artist"]["name"], obj["title"],
                            obj["album"]["title"], obj["duration"],
                            "; ".join(t.artists) if t else "", t.title if t else "",
                            round(t.duration_ms / 1000) if t and t.duration_ms else "", r.status if r else ""])
        overrides.ensure(cfg.overrides_path)
        print(f"{len(uploads)} uploaded MP3s on account {gw.user_id}, written to {out}.")
        for obj, pair, score in rows:
            where = f"[{pair[0].position}] {_label(pair[0])}" if pair else "no undecided row resembles it"
            print(f"  {obj['id']} {obj['artist']['name']} - {obj['title']} ({obj['duration']}s) "
                  f"-> {score:.2f} {where}")
        print(f"Copy the first three columns of each row you agree with into {cfg.overrides_path}, then run resolve.")
    return 0


def cmd_add(cfg: config.Config, args) -> int:
    if not cfg.deezer_user_id:
        print("DEEZER_USER_ID is not set.", file=sys.stderr)
        return 2
    size = args.batch or cfg.batch_size
    with State(cfg.state_path) as st:
        pending = st.pending_adds()
        if not pending:
            print("Nothing left to add.")
            return 0
        rows = pending[:size]
        blocking = st.blocking(rows[-1][0].position)
        if blocking:
            print(f"The batch would end at position {rows[-1][0].position}; these rows need a decision first:")
            for t, status in blocking:
                print(f"  [{t.position}] {status}: {_label(t)}")
            print("Run review, record decisions in data/overrides.csv, then resolve.")
            return 1
        print(f"Batch of {len(rows)}: positions {rows[0][0].position}-{rows[-1][0].position}, "
              f"{len(pending) - len(rows)} remain after it.")
        if args.dry_run:
            return 0

        batch = st.next_batch()
        total = favourites.reconcile(st, cfg.deezer_user_id, batch, args.allow_existing)
        rows = st.pending_adds()[:size]
        with browser.persistent_context(cfg.browser_profile, headless=cfg.headless, channel=cfg.browser_channel) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.deezer.com/en/")
            browser.wait_security_check(page)
            gw = GwSession(page)
            if gw.user_id != cfg.deezer_user_id:
                print(f"Logged-in user {gw.user_id} differs from DEEZER_USER_ID {cfg.deezer_user_id}.", file=sys.stderr)
                return 2
            favourites.add_all(st, gw, cfg.deezer_user_id, rows, batch, cfg.add_delay_min, cfg.add_delay_max, total)
        print(f"Batch {batch} done: {st.count('adds')} added so far, {len(st.pending_adds())} to go.")
        time.sleep(2)
        return _verify(cfg, st)


def cmd_verify(cfg: config.Config, args) -> int:
    with State(cfg.state_path) as st:
        if args.against:
            _diff_export(st, Path(args.against))
        if not cfg.deezer_user_id:
            print("DEEZER_USER_ID is not set.", file=sys.stderr)
            return 2
        return _verify(cfg, st)


def _verify(cfg: config.Config, st: State) -> int:
    report = verify.check(st, cfg.deezer_user_id)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / f"verify-{datetime.now():%Y%m%d-%H%M%S}.csv"
    verify.write(report, out)
    if report.ok:
        print(f"Verify OK: {len(report.rows)} favourites, time_add strictly increasing along position. Report {out}.")
        return 0
    print(f"Verify found {len(report.issues)} issues. Report {out}.")
    for issue in report.issues[:20]:
        print(f"  {issue}")
    return 1


def _diff_export(st: State, path: Path) -> None:
    fresh = {t.source_uri: t for t in exportify.read(path).tracks}
    known = {t.source_uri: t for t in st.tracks()}
    added = [t for u, t in fresh.items() if u not in known]
    removed = [t for u, t in known.items() if u not in fresh]
    print(f"{path.name}: {len(added)} liked since import, {len(removed)} unliked since import.")
    for t in added:
        print(f"  + {t.added_at} {_label(t)}")
    for t in removed:
        print(f"  - [{t.position}] {_label(t)}")


def cmd_status(cfg: config.Config, _args) -> int:
    with State(cfg.state_path) as st:
        name = st.get_meta("import_file")
        if not name:
            print("Nothing imported.")
            return 1
        print(f"Imported {st.count('tracks')} tracks from {name} at {st.get_meta('import_at')}.")
        _print_counts(st)
        pending = st.pending_adds()
        print(f"Adds recorded: {st.count('adds')}; {len(pending)} matched rows still to add.")
        if pending:
            end = pending[:cfg.batch_size][-1][0].position
            blocking = st.blocking(end)
            print(f"Next batch would cover positions {pending[0][0].position}-{end}; "
                  f"{len(blocking)} rows up to there still need a decision.")
    return 0


def _label(t) -> str:
    return f"{' / '.join(t.artists)} - {t.title} ({round((t.duration_ms or 0) / 1000)}s)"


def _print_counts(st: State) -> None:
    counts = st.resolution_counts()
    total = sum(n for _, _, n in counts)
    print(f"Resolved {total}/{st.count('tracks')}: " + ", ".join(
        f"{status}{'/' + method if method else ''} {n}" for status, method, n in counts))


def cmd_clear_favourites(cfg: config.Config, args) -> int:
    if not cfg.deezer_user_id:
        print("DEEZER_USER_ID is not set.", file=sys.stderr)
        return 2
    favs = catalog.user_favourites(cfg.deezer_user_id)
    print(f"{len(favs)} favourites on account {cfg.deezer_user_id}.")
    if not favs:
        return 0
    if not args.yes:
        print("Re-run with --yes to remove them all.")
        return 1

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    backup = cfg.reports_dir / f"favourites-backup-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(
        [{k: t.get(k) for k in ("id", "title", "duration", "time_add")} | {"artist": t["artist"]["name"]} for t in favs],
        indent=1))
    print(f"Backup written to {backup}.")

    ids = [t["id"] for t in favs]
    with browser.persistent_context(cfg.browser_profile, headless=cfg.headless, channel=cfg.browser_channel) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.deezer.com/en/")
        browser.wait_security_check(page)
        gw = GwSession(page)
        if gw.user_id != cfg.deezer_user_id:
            print(f"Logged-in user {gw.user_id} differs from DEEZER_USER_ID {cfg.deezer_user_id}.", file=sys.stderr)
            return 2

        gw.remove_favourites(ids[:1])
        time.sleep(1.5)
        total = catalog.favourites_total(cfg.deezer_user_id)
        if total != len(ids) - 1:
            print(f"Probe removal not reflected: public total is {total}, expected {len(ids) - 1}. Stopping.", file=sys.stderr)
            return 1
        print("Probe removal confirmed.")

        rest = ids[1:]
        for i in range(0, len(rest), args.batch):
            chunk = rest[i:i + args.batch]
            gw.remove_favourites(chunk)
            print(f"  removed {1 + i + len(chunk)}/{len(ids)}")
            time.sleep(args.delay)

    time.sleep(2)
    total = catalog.favourites_total(cfg.deezer_user_id)
    print(f"Public API now reports {total} favourites.")
    if total:
        return 1
    with State(cfg.state_path) as st:
        forgotten = st.clear_adds()
    if forgotten:
        print(f"{forgotten} recorded adds forgotten; add starts over from position 0.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="s2d")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="open a browser window to log in to Deezer once")
    sub.add_parser("whoami", help="check whether the stored Deezer session is present")
    imp = sub.add_parser("import", help="load an Exportify CSV into the state file, ordered by Added At")
    imp.add_argument("csv", nargs="?", help="path to the CSV; defaults to the single CSV in data/export")
    res = sub.add_parser("resolve", help="map imported tracks to Deezer tracks by ISRC, then search")
    res.add_argument("--retry", action="store_true", help="also re-resolve unmatched and needs-review rows")
    res.add_argument("--limit", type=int, default=0)
    sub.add_parser("review", help="write unmatched and needs-review rows to data/reports/review.csv")
    rec = sub.add_parser("reconcile", help="merge liked local files from a Spotify data export (YourLibrary.json)")
    rec.add_argument("library", help="path to YourLibrary.json from Spotify's Download your data")
    rec.add_argument("--apply", action="store_true", help="insert the placed tracks and renumber positions")
    sub.add_parser("uploads", help="list the MP3s uploaded to Deezer and match them against undecided rows")
    add = sub.add_parser("add", help="favourite the next batch of matched tracks on Deezer, in position order")
    add.add_argument("--batch", type=int, default=0, help="tracks in this run; defaults to BATCH_SIZE")
    add.add_argument("--allow-existing", action="store_true", help="tolerate favourites this tool did not add")
    add.add_argument("--dry-run", action="store_true", help="show the batch and any blocking rows only")
    ver = sub.add_parser("verify", help="check Deezer favourites against recorded adds and position order")
    ver.add_argument("--against", help="fresh Exportify CSV to diff against the imported one")
    sub.add_parser("status", help="show what is imported and how far the migration has got")
    clear = sub.add_parser("clear-favourites", help="remove every favourite track from the Deezer account")
    clear.add_argument("--yes", action="store_true")
    clear.add_argument("--batch", type=int, default=25)
    clear.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)
    cfg = config.load()
    commands = {
        "login": cmd_login,
        "whoami": cmd_whoami,
        "import": cmd_import,
        "resolve": cmd_resolve,
        "review": cmd_review,
        "reconcile": cmd_reconcile,
        "uploads": cmd_uploads,
        "add": cmd_add,
        "verify": cmd_verify,
        "status": cmd_status,
        "clear-favourites": cmd_clear_favourites,
    }
    try:
        return commands[args.command](cfg, args)
    except browser.ProfileInUse as e:
        print(f"Browser profile {e} is open in another window. Close it and retry.", file=sys.stderr)
        return 2
    except catalog.ApiError as e:
        print(f"Deezer API error, stopping: {e}", file=sys.stderr)
        return 1
    except (favourites.AddError, GwError) as e:
        print(f"Stopping: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
