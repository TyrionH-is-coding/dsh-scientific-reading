from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scientific_reading.mineru_local import LocalMineruProvider


def test_parse_finishes_when_exited_cli_leaves_a_child_holding_output(tmp_path: Path) -> None:
    """MinerU's local API child must not keep the caller waiting on a pipe."""
    stop = tmp_path / "stop-child"
    child = tmp_path / "child.py"
    child.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "deadline = time.monotonic() + 6\n"
        "while not Path(sys.argv[1]).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    cli = tmp_path / "mineru_cli.py"
    cli.write_text(
        "import json, subprocess, sys\n"
        "from pathlib import Path\n"
        "root = Path(__file__).parent\n"
        "subprocess.Popen([sys.executable, str(root / 'child.py'), str(root / 'stop-child')], "
        "stdout=sys.stdout, stderr=sys.stderr, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        "output = Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "output.mkdir(parents=True, exist_ok=True)\n"
        "(output / 'paper_content_list.json').write_text(json.dumps([{'type': 'text', 'text': 'fixture'}]), encoding='utf-8')\n",
        encoding="utf-8",
    )

    def runner(args, **kwargs):
        kwargs["timeout"] = 1
        return subprocess.run([sys.executable, str(cli), *args[1:]], **kwargs)

    provider = LocalMineruProvider(
        executable=str(cli), runner=runner, version="3.4.5"
    )
    try:
        result = provider.parse(tmp_path / "paper.pdf", tmp_path / "raw", "auto", lambda: None)
        assert (result.raw_root / "paper_content_list.json").is_file()
    finally:
        stop.touch()
