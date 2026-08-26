from __future__ import annotations

import os
import subprocess


_IS_WINDOWS = os.name == "nt"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hidden_window_kwargs() -> dict[str, int]:
    if not _IS_WINDOWS:
        return {}
    return {"creationflags": _CREATE_NO_WINDOW}
