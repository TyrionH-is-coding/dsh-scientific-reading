"""Read-only source fixture audit: work only on a copy in the supplied output root."""
import json
import shutil
import sys
from pathlib import Path
from scientific_reading.workspace import PaperWorkspace
from scientific_reading.full_read_service import FullReadService
from scientific_reading.normalization_upgrade import upgrade_unfinished_normalization

source, output = map(Path, sys.argv[1:])
if output.exists():
    raise RuntimeError("audit output must be new")
output = output / source.name
shutil.copytree(source, output)
workspace = PaperWorkspace(root=output)
assert upgrade_unfinished_normalization(workspace)
assert not upgrade_unfinished_normalization(workspace)
plan = FullReadService().prepare(workspace)
parsed = output / "parsed" / "mineru"
raw = json.loads(next((parsed / "raw").rglob("*_content_list.json")).read_text(encoding="utf-8"))
blocks = json.loads((parsed / "source_map.json").read_text(encoding="utf-8"))["blocks"]
equations = [(i, x) for i, x in enumerate(raw) if x["type"] == "equation"]
for i, x in equations:
    matches = [b for b in blocks if b["source_index"] == i]
    assert len(matches) == 1 and matches[0]["text"] == x["text"].strip()
    assert matches[0]["page"] == x["page_idx"] + 1
report = json.loads((parsed / "parse_report.json").read_text(encoding="utf-8"))
assert not any("equation" in w or "level_conflict" in w for w in report["warnings"])
print(json.dumps({"equations_preserved": len(equations), "blocks": len(blocks), "batches": len(plan.batch_paths), "warnings": report["warnings"], "headings": [{"text": b["text"], "level": b["heading_level"]} for b in blocks if b.get("heading_level")]}, ensure_ascii=False))
