import pytest

from scientific_reading.library_service import LibraryService
from scientific_reading.library_views import LibraryViews


def test_theme_presets_persist_without_accepting_arbitrary_colors(tmp_path):
    library = LibraryService(tmp_path)
    views = LibraryViews(library)
    assert views.theme()["id"] == "paper"
    assert [item["id"] for item in views.theme()["presets"]] == ["paper", "light", "dark", "mist"]
    for theme in views.theme()["presets"]:
        saved = views.theme_save({"preset": theme["id"]})
        assert saved["paper"] == theme["paper"]
        assert saved["ink"] == theme["ink"]
        assert LibraryViews(LibraryService(tmp_path)).theme()["id"] == theme["id"]
    for value in ({"accent": "#123456"}, {"preset": "custom"}, {"preset": {"id": "dark"}}):
        with pytest.raises(ValueError, match="display_theme_invalid"):
            views.theme_save(value)
    assert views.theme()["id"] == "mist"


def test_legacy_color_is_read_without_rewriting_user_metadata(tmp_path):
    library = LibraryService(tmp_path)
    with library.conn:
        library.conn.execute("INSERT INTO library_meta(key,value) VALUES('display.theme','#123456')")
    assert LibraryViews(library).theme()["id"] == "paper"
    assert library.conn.execute("SELECT value FROM library_meta WHERE key='display.theme'").fetchone()[0] == "#123456"
