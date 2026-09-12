import csv
import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from helpers import FakePage, favourite, ns, obj, resolution, track, write_csv
from s2d import cli, config
from s2d.deezer import catalog
from s2d.deezer.web import GwError
from s2d.state import State
from test_exportify import APP, row


def seed(cfg, n=3, statuses=("matched", "matched", "matched")):
    with State(cfg.state_path) as st:
        st.replace_tracks([track(i, isrc=f"XX{i}") for i in range(n)])
        st.set_meta("import_file", "liked.csv")
        st.set_meta("import_at", "2020-01-01T00:00:00")
        for i, status in enumerate(statuses):
            method, deezer_id = (None, None) if status == "unmatched" else ("isrc", 10 + i)
            st.upsert_resolution(resolution(f"spotify:track:{i}", status, method, deezer_id, None))


def tracks(cfg):
    with State(cfg.state_path) as st:
        return [(t.position, t.source_uri) for t in st.tracks()]


@pytest.fixture
def browsered(monkeypatch, fake_gw):
    page = FakePage()

    @contextmanager
    def fake_context(*_a, **_k):
        yield SimpleNamespace(pages=[page], new_page=lambda: page)

    monkeypatch.setattr(cli.browser, "persistent_context", fake_context)
    monkeypatch.setattr(cli.browser, "wait_security_check", lambda _page: None)
    monkeypatch.setattr(cli, "GwSession", lambda _page: fake_gw)
    return fake_gw


def test_export_file(cfg):
    cfg.export_dir.mkdir(parents=True)
    with pytest.raises(SystemExit, match="found 0"):
        cli._export_file(cfg, None)
    (cfg.export_dir / "a.csv").touch()
    assert cli._export_file(cfg, None) == cfg.export_dir / "a.csv"
    (cfg.export_dir / "b.csv").touch()
    with pytest.raises(SystemExit, match="found 2"):
        cli._export_file(cfg, None)
    assert cli._export_file(cfg, "x.csv").name == "x.csv"


def test_import(cfg, capsys):
    write_csv(
        cfg.export_dir / "liked.csv",
        APP,
        [row(uri="spotify:track:a"), row(uri="spotify:track:b", added="2019-01-01T00:00:00Z")],
    )
    assert cli.cmd_import(cfg, ns()) == 0
    assert "Imported 2 tracks from liked.csv (exportify.app)" in capsys.readouterr().out
    with State(cfg.state_path) as st:
        assert st.get_meta("import_file") == "liked.csv"
        assert len(st.get_meta("import_sha256") or "") == 64
        assert [t.source_uri for t in st.tracks()] == ["spotify:track:b", "spotify:track:a"]

    assert cli.cmd_import(cfg, ns()) == 0
    assert "already imported" in capsys.readouterr().out


def test_import_refuses_to_replace(cfg, capsys):
    write_csv(cfg.export_dir / "liked.csv", APP, [row()])
    assert cli.cmd_import(cfg, ns()) == 0
    write_csv(cfg.export_dir / "liked.csv", APP, [row(), row(uri="spotify:track:b")])
    with State(cfg.state_path) as st:
        st.record_add(0, 10, 1, "2020-01-01T00:00:00")
    assert cli.cmd_import(cfg, ns()) == 1
    assert "1 adds are recorded" in capsys.readouterr().err
    with State(cfg.state_path) as st:
        st.clear_adds()
        st.set_meta("reconcile_file", "YourLibrary.json")
    assert cli.cmd_import(cfg, ns()) == 1
    assert "merged in by reconcile" in capsys.readouterr().err
    assert len(tracks(cfg)) == 1


@pytest.fixture
def library(cfg, tmp_path):
    seed(cfg, 2)
    path = tmp_path / "YourLibrary.json"
    lib = {
        "tracks": [{"uri": "spotify:track:0", "track": "Song A", "artist": "Artist A", "album": "Album A"}],
        "other": ["spotify:local:Artist+L:Album+L:Song+L:180", "spotify:local:Artist+M:Album+M:Song+M:60"],
    }
    path.write_text(json.dumps(lib))
    return path


def fill(cfg, dates):
    rows = list(csv.DictReader(cfg.placements_path.open()))
    for r, d in zip(rows, dates, strict=True):
        r["added_at"] = d
    fields: list[str] = list(rows[0])
    with cfg.placements_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_reconcile_lists_rows_needing_dates(cfg, library, capsys):
    assert cli.cmd_reconcile(cfg, ns(library=str(library))) == 1
    out = capsys.readouterr().out
    assert "3 liked tracks, 2 not imported (2 local files), 1 imported but no longer liked." in out
    assert "2 of 2 rows" in out
    assert [r["source_uri"] for r in csv.DictReader(cfg.placements_path.open())] == [
        "spotify:local:Artist+L:Album+L:Song+L:180",
        "spotify:local:Artist+M:Album+M:Song+M:60",
    ]


def test_reconcile_preview_and_refusal(cfg, library, capsys):
    cli.cmd_reconcile(cfg, ns(library=str(library)))
    fill(cfg, ["2020-01-01", "SKIP"])
    before = tracks(cfg)
    assert cli.cmd_reconcile(cfg, ns(library=str(library))) == 0
    assert "Re-run with --apply" in capsys.readouterr().out
    assert tracks(cfg) == before

    with State(cfg.state_path) as st:
        st.record_add(0, 10, 1, "2020-01-01T00:00:00")
    assert cli.cmd_reconcile(cfg, ns(library=str(library), apply=True)) == 1
    assert "Refusing: 1 adds are recorded" in capsys.readouterr().err
    assert tracks(cfg) == before


def test_reconcile_apply_renumbers(cfg, library, capsys):
    cli.cmd_reconcile(cfg, ns(library=str(library)))
    fill(cfg, ["2020-01-01", "SKIP"])
    assert cli.cmd_reconcile(cfg, ns(library=str(library), apply=True)) == 0
    assert "Inserted 1 tracks; 3 positions renumbered" in capsys.readouterr().out
    assert tracks(cfg) == [
        (0, "spotify:track:0"),
        (1, "spotify:track:1"),
        (2, "spotify:local:Artist+L:Album+L:Song+L:180"),
    ]
    with State(cfg.state_path) as st:
        assert st.get_meta("reconcile_file") == "YourLibrary.json"
        assert [t.position for t in st.pending_tracks(retry=False)] == [2]
    assert [r["source_uri"] for r in csv.DictReader(cfg.placements_path.open())] == [
        "spotify:local:Artist+M:Album+M:Song+M:60"
    ]


def test_add_dry_run(cfg, capsys):
    assert cli.cmd_add(replace(cfg, deezer_user_id=None), ns(dry_run=True)) == 2
    seed(cfg, 3, ("matched", "unmatched", "matched"))
    assert cli.cmd_add(cfg, ns(dry_run=True)) == 1
    assert "[1] unmatched" in capsys.readouterr().out
    assert cli.cmd_add(cfg, ns(dry_run=True, batch=1)) == 0
    assert "Batch of 1: positions 0-0, 1 remain after it." in capsys.readouterr().out
    with State(cfg.state_path) as st:
        st.record_add(0, 10, 1, "2020-01-01T00:00:00")
        st.record_add(2, 12, 1, "2020-01-01T00:00:01")
    assert cli.cmd_add(cfg, ns(dry_run=True)) == 0
    assert "Nothing left to add." in capsys.readouterr().out


def test_add_favourites_then_verifies(cfg, fake_catalog, browsered, capsys):
    seed(cfg, 2)
    assert cli.cmd_add(cfg, ns()) == 0
    out = capsys.readouterr().out
    assert "Batch 1 done: 2 added so far, 0 to go." in out
    assert "Verify OK: 2 favourites" in out
    with State(cfg.state_path) as st:
        assert [(a["position"], a["deezer_id"]) for a in st.adds()] == [(0, 10), (1, 11)]
    assert len(list(cfg.reports_dir.glob("verify-*.csv"))) == 1


def test_add_refuses_other_account(cfg, fake_catalog, browsered, capsys):
    seed(cfg, 1)
    browsered.user_id = "2"
    assert cli.cmd_add(cfg, ns()) == 2
    assert "differs from DEEZER_USER_ID" in capsys.readouterr().err
    with State(cfg.state_path) as st:
        assert st.count("adds") == 0


def test_review(cfg):
    seed(cfg, 3, ("unmatched", "needs-review", "matched"))
    assert cli.cmd_review(cfg, ns()) == 0
    rows = list(csv.DictReader((cfg.reports_dir / "review.csv").open()))
    assert [(r["position"], r["status"]) for r in rows] == [("0", "unmatched"), ("1", "needs-review")]
    assert cfg.overrides_path.read_text().startswith("source_uri,")


def test_resolve(cfg, fake_catalog, capsys):
    assert cli.cmd_resolve(cfg, ns()) == 1
    with State(cfg.state_path) as st:
        st.replace_tracks([track(0, isrc="XX1"), track(1, isrc="XX1"), track(2, title="Nothing Like It")])
    fake_catalog.add(obj(1, isrc="XX1"))
    assert cli.cmd_resolve(cfg, ns()) == 0
    out = capsys.readouterr().out
    assert "0 overrides applied; resolving 3 tracks." in out
    assert "[2] unmatched" in out
    assert "1 duplicate rows re-flagged." in out
    with State(cfg.state_path) as st:
        assert [r.status for _, r in st.resolved()] == ["matched", "dup-skip", "unmatched"]


def test_status(cfg, capsys):
    assert cli.cmd_status(cfg, ns()) == 1
    seed(cfg, 3, ("matched", "unmatched", "matched"))
    assert cli.cmd_status(cfg, ns()) == 0
    out = capsys.readouterr().out
    assert "Imported 3 tracks from liked.csv" in out
    assert "Adds recorded: 0; 2 matched rows still to add." in out
    assert "1 rows up to there still need a decision." in out


def test_verify_diffs_fresh_export(cfg, fake_catalog, tmp_path, capsys):
    seed(cfg, 2)
    fresh = write_csv(tmp_path / "fresh.csv", APP, [row(uri="spotify:track:1"), row(uri="spotify:track:9")])
    assert cli.cmd_verify(replace(cfg, deezer_user_id=None), ns(against=str(fresh))) == 2
    assert "fresh.csv: 1 liked since import, 1 unliked since import." in capsys.readouterr().out
    assert cli.cmd_verify(cfg, ns()) == 0
    assert "Verify OK: 0 favourites" in capsys.readouterr().out


def test_clear_favourites(cfg, fake_catalog, browsered, capsys):
    assert cli.cmd_clear_favourites(cfg, ns()) == 0
    fake_catalog.favourites = [favourite(10, 1), favourite(11, 2), favourite(12, 3)]
    assert cli.cmd_clear_favourites(cfg, ns()) == 1
    assert "Re-run with --yes" in capsys.readouterr().out
    with State(cfg.state_path) as st:
        st.record_add(0, 10, 1, "2020-01-01T00:00:00")
    assert cli.cmd_clear_favourites(cfg, ns(yes=True, batch=1, delay=0)) == 0
    out = capsys.readouterr().out
    assert "Probe removal confirmed." in out
    assert "1 recorded adds forgotten" in out
    assert browsered.removed == [10, 11, 12]
    [backup] = cfg.reports_dir.glob("favourites-backup-*.json")
    assert [t["id"] for t in json.loads(backup.read_text())] == [10, 11, 12]
    with State(cfg.state_path) as st:
        assert st.count("adds") == 0


def test_main_maps_errors_to_exit_codes(cfg, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda: cfg)
    assert cli.main(["status"]) == 1

    def raising(exc):
        def cmd(_cfg, _args):
            raise exc

        return cmd

    monkeypatch.setattr(cli, "cmd_status", raising(catalog.ApiError("quota")))
    assert cli.main(["status"]) == 1
    monkeypatch.setattr(cli, "cmd_status", raising(GwError("token")))
    assert cli.main(["status"]) == 1
    monkeypatch.setattr(cli, "cmd_status", raising(cli.browser.ProfileInUse("p")))
    assert cli.main(["status"]) == 2
    assert "is open in another window" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main([])
