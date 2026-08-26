from scientific_reading import subprocess_utils


def test_hidden_window_kwargs_use_create_no_window_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", True)
    monkeypatch.setattr(subprocess_utils, "_CREATE_NO_WINDOW", 0x08000000)

    assert subprocess_utils.hidden_window_kwargs() == {"creationflags": 0x08000000}


def test_hidden_window_kwargs_do_not_change_non_windows_launches(monkeypatch) -> None:
    monkeypatch.setattr(subprocess_utils, "_IS_WINDOWS", False)

    assert subprocess_utils.hidden_window_kwargs() == {}
