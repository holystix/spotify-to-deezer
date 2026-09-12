import json

import pytest

from s2d.sources import spotify_export


def test_read_tracks_and_local_files(tmp_path):
    lib = {
        "tracks": [{"uri": "spotify:track:a", "track": "Song A", "artist": "Artist A, Artist B", "album": "Album A"}],
        "other": ["spotify:local:Artist+L:Album+L:Song+L:180", "spotify:playlist:p"],
    }
    path = tmp_path / "YourLibrary.json"
    path.write_text(json.dumps(lib))
    items = spotify_export.read(path)
    assert [i.uri for i in items] == ["spotify:track:a", "spotify:local:Artist+L:Album+L:Song+L:180"]
    assert items[0].artists == ("Artist A", "Artist B")
    assert items[0].duration_ms is None
    assert not items[0].is_local
    assert items[1] == spotify_export.Item(items[1].uri, "Song L", ("Artist L",), "Album L", 180_000, True)


def test_local_decodes_and_tolerates_missing_seconds():
    i = spotify_export._local("spotify:local:A%26B:Album:Caf%C3%A9+Song:")
    assert i.artists == ("A&B",)
    assert i.title == "Café Song"
    assert i.duration_ms is None


def test_local_rejects_wrong_shape():
    with pytest.raises(ValueError, match="unexpected local file URI"):
        spotify_export._local("spotify:local:a:b:c")


def test_artists_drops_blanks():
    assert spotify_export._artists("Artist A, , Artist B") == ("Artist A", "Artist B")
