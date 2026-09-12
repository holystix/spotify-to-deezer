import pytest

from helpers import write_csv
from s2d import overrides
from s2d.overrides import Override

H = overrides.HEADER


def test_missing_file_is_empty(tmp_path):
    assert overrides.read(tmp_path / "none.csv") == []


def test_read_accepts_ids_urls_and_skip(tmp_path):
    rows = [
        ["spotify:track:a", "123", "bare id"],
        ["spotify:track:b", "https://www.deezer.com/en/track/456", "url"],
        ["spotify:track:c", "-7", "upload"],
        ["spotify:track:d", "track/-8", ""],
        ["spotify:track:e", "skip", "gone"],
        ["", "", "blank row"],
    ]
    out = overrides.read(write_csv(tmp_path / "o.csv", H, rows, encoding="utf-8-sig"))
    assert out == [
        Override("spotify:track:a", 123, "bare id"),
        Override("spotify:track:b", 456, "url"),
        Override("spotify:track:c", -7, "upload"),
        Override("spotify:track:d", -8, ""),
        Override("spotify:track:e", None, "gone"),
    ]


@pytest.mark.parametrize("row", [["", "123", ""], ["spotify:track:a", "abc", ""], ["spotify:track:a", "", "note only"]])
def test_read_rejects_bad_rows(tmp_path, row):
    path = write_csv(tmp_path / "o.csv", H, [["spotify:track:z", "1", ""], row])
    with pytest.raises(ValueError, match=r"o\.csv:3: need a source_uri"):
        overrides.read(path)


def test_ensure_creates_header_once(tmp_path):
    path = tmp_path / "data" / "overrides.csv"
    overrides.ensure(path)
    assert path.read_text() == "source_uri,deezer_id,note\n"
    path.write_text("custom")
    overrides.ensure(path)
    assert path.read_text() == "custom"
