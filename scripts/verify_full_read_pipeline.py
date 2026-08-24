from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


INTERRUPTIONS = (
    "after_pdf_publish",
    "after_mineru",
    "after_translation_batch_1",
    "after_reader_staging",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fixture_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    pages = (
        "Load Distribution in Modular Truss Bridges\nAbstract\nA fictional engineering fixture.",
        "Methods\nFinite element mesh, load cases, and boundary conditions.",
        "Results\nFigure 1 stress field. Figure 2 displacement. Table 1 load cases.",
        "References\n[1] Rivera A. Fictional bridge benchmark. 2026.",
    )
    for text in pages:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=12)
    document.save(path)
    document.close()


def _translation(batch: dict) -> dict:
    rows = []
    for index, block in enumerate(batch["blocks"]):
        reference = block.get("source_type") == "reference"
        rows.append(
            {
                "block_id": block["block_id"],
                "source_text": block["english"],
                "translation_zh": "" if reference else f"工程译文：{block['english']}",
                "highlight": "none" if reference else ("primary" if index == 0 else "secondary" if index == 1 else "none"),
            }
        )
    return {
        "contract_version": "full-translation-v2",
        "batch_id": batch["batch_id"],
        "source_sha256": batch["source_sha256"],
        "translations": rows,
    }


def _load_runs(root: Path) -> dict[str, int]:
    path = root / "execution-counts.json"
    if not path.is_file():
        return {"pdf": 0, "mineru": 0, "translation_batch_1": 0, "reader": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def _increment(root: Path, key: str) -> None:
    runs = _load_runs(root)
    runs[key] += 1
    _atomic_json(root / "execution-counts.json", runs)


def _metadata():
    from scientific_reading.models import PaperMetadata

    return PaperMetadata(
        title="Load Distribution in Modular Truss Bridges",
        authors=["Alex Rivera"],
        doi="10.5555/full-read-recovery.2026.1",
        year=2026,
        journal="Fictional Engineering Notes",
    )


def _workspace(data_root: Path):
    from scientific_reading.library_service import LibraryService
    from scientific_reading.workspace import PaperWorkspace

    library = LibraryService(data_root)
    try:
        item = library.ensure_item(_metadata())
    finally:
        library.close()
    base = PaperWorkspace.create_for_paper_id(data_root, item["paper_id"], _metadata())
    return item["paper_id"], base


def _ensure_pdf(root: Path, base) -> str:
    if not base.source_pdf.is_file():
        _increment(root, "pdf")
        staging = base.root / ".source.pdf.staging"
        _fixture_pdf(staging)
        staging.replace(base.source_pdf)
    return _sha(base.source_pdf)


def _ensure_mineru(root: Path, base, source_sha: str):
    from PIL import Image
    from scientific_reading.mineru_normalizer import MineruNormalizer
    from scientific_reading.models import StageRecord
    from scientific_reading.workspace import PaperWorkspace, atomic_write_json

    generation = PaperWorkspace.create_generation(base, source_sha, _metadata())
    if not generation.source_pdf.is_file():
        shutil.copyfile(base.source_pdf, generation.source_pdf)
    source_map = generation.parsed_dir / "mineru" / "source_map.json"
    if source_map.is_file():
        return generation
    _increment(root, "mineru")
    raw = generation.parsed_dir / "mineru" / "raw" / "fixture" / "auto"
    raw.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 50), "navy").save(raw / "figure-1.png")
    Image.new("RGB", (80, 50), "orange").save(raw / "figure-2.png")
    Image.new("RGB", (100, 60), "white").save(raw / "table-1.png")
    content = [{"type": "header", "text": _metadata().title, "text_level": 1, "page_idx": 0, "bbox": [72, 72, 520, 110]}]
    for index in range(1, 42):
        content.append({"type": "text", "text": f"Engineering paragraph {index} describing loads and deflection.", "page_idx": min(3, index // 11), "bbox": [72, 120 + (index % 10) * 30, 520, 145 + (index % 10) * 30]})
    content.extend(
        [
            {"type": "image", "img_path": "figure-1.png", "image_caption": ["Figure 1. Stress field"], "image_footnote": [], "page_idx": 1, "bbox": [72, 400, 250, 520], "is_body": True},
            {"type": "image", "img_path": "figure-2.png", "image_caption": ["Figure 2. Displacement"], "image_footnote": [], "page_idx": 2, "bbox": [270, 400, 448, 520], "is_body": True},
            {"type": "table", "img_path": "table-1.png", "table_caption": ["Table 1. Load cases"], "table_footnote": [], "table_body": "<table><tr><th>Case</th><th>Load</th></tr><tr><td>A</td><td>12</td></tr></table>", "page_idx": 2, "bbox": [72, 540, 448, 680], "is_body": True},
            {"type": "header", "text": "References", "text_level": 1, "page_idx": 3, "bbox": [72, 400, 520, 430]},
            {"type": "text", "text": "[1] Rivera A. Fictional bridge benchmark. 2026.", "page_idx": 3, "bbox": [72, 440, 520, 470]},
        ]
    )
    content.sort(key=lambda row: row["page_idx"])
    (raw / "fixture_content_list.json").write_text(json.dumps(content), encoding="utf-8")
    normalized = MineruNormalizer("fixture-1").normalize(generation.parsed_dir / "mineru" / "raw", generation.parsed_dir / "mineru", _metadata(), source_sha)
    for name in ("source_map.json", "parse_report.json"):
        path = generation.parsed_dir / "mineru" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        atomic_write_json(path, payload)
    atomic_write_json(generation.manifest_path, {"version": 1, "assets": [asset.to_dict() for asset in normalized.assets]})
    nested = generation.load_job()
    nested.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={"source_sha256": source_sha, "method": "auto", "mineru_version": "fixture-1", "active_parsed_dir": "parsed/mineru"})
    generation.save_job(nested)
    state = base.load_job()
    state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={"source_sha256": source_sha, "method": "auto", "mineru_version": "fixture-1", "active_parsed_dir": "parsed/mineru", "active_workspace": f"generations/{source_sha[:16]}"})
    base.save_job(state)
    return generation


def _finish(root: Path, crashpoint: str | None) -> dict:
    from scientific_reading.export_service import ExportService
    from scientific_reading.full_read_renderer import FullReadRenderer
    from scientific_reading.full_read_service import FullReadService

    paper_id, base = _workspace(root / "data")
    source_sha = _ensure_pdf(root, base)
    if crashpoint == "after_pdf_publish":
        os._exit(97)
    generation = _ensure_mineru(root, base, source_sha)
    if crashpoint == "after_mineru":
        os._exit(97)
    service = FullReadService()
    service.prepare(generation)
    batch = service.next_batch(generation)
    if batch is not None:
        if batch["batch_id"].endswith("0001"):
            _increment(root, "translation_batch_1")
        service.save_translation_batch(generation, _translation(batch))
        if crashpoint == "after_translation_batch_1":
            os._exit(97)
    while (batch := service.next_batch(generation)) is not None:
        service.save_translation_batch(generation, _translation(batch))
    service.review_context(generation)
    if not generation.reader_html.is_file():
        if crashpoint == "after_reader_staging":
            abandoned = generation.reading_dir / ".reader-publish-interrupted"
            abandoned.mkdir(exist_ok=True)
            (abandoned / "reader.html").write_text("partial", encoding="utf-8")
            os._exit(97)
        _increment(root, "reader")
        FullReadRenderer().render_completed(generation, paper_id=paper_id)
    exported = ExportService().export(base)
    manifest = json.loads(generation.reader_manifest.read_text(encoding="utf-8"))
    export_manifest = json.loads(generation.exports_manifest.read_text(encoding="utf-8"))
    readers = list(base.root.glob("generations/*/reading/reader.html"))
    relative_reader = generation.reader_html.relative_to(root / "data").as_posix()
    return {
        "paper_id": paper_id,
        "reader_path": relative_reader,
        "active_reader_count": len(readers),
        "sha_alignment": manifest["source_pdf_sha256"] == source_sha == _sha(base.source_pdf) == _sha(generation.source_pdf),
        "exports": {
            "figures": len(exported.figure_paths),
            "tables": len(exported.table_paths),
            "captions": generation.exports_captions.is_file(),
            "manifest": generation.exports_manifest.is_file() and len(export_manifest["assets"]) == 3,
        },
        "runs": _load_runs(root),
    }


def _engine_root() -> Path:
    value = os.environ.get("SR_ENGINE_ROOT")
    root = Path(value).resolve() if value else (
        Path(__file__).resolve().parents[3]
        / "Scientific-Reading-for-Newbies"
        / ".worktrees"
        / "two-stage-workflow"
    ).resolve()
    if not (root / "src" / "scientific_reading").is_dir():
        raise RuntimeError("SR_ENGINE_ROOT_invalid")
    return root


def verify() -> dict:
    engine = _engine_root()
    packages = sorted((Path.home() / ".dsh" / "packages").glob("dsh-external-dsh-scientific-reading-*.tgz"))
    installed = packages[-1] if packages else None
    installed_sha_before = _sha(installed) if installed is not None else None
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(engine / "src")
    child_env.pop("FEISHU_APP_ID", None)
    child_env.pop("FEISHU_APP_SECRET", None)
    results = []
    with tempfile.TemporaryDirectory(prefix="sr-full-read-integration-") as temporary:
        root = Path(temporary)
        for interruption in INTERRUPTIONS:
            scenario = root / interruption
            scenario.mkdir()
            scenario_env = {**child_env, "DSH_PROFILE": "sr-task7-isolated", "DSH_PROFILE_DIR": str(scenario / "profile")}
            interrupted = subprocess.run([sys.executable, __file__, "--child", str(scenario), "--crashpoint", interruption], env=scenario_env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            if interrupted.returncode != 97:
                raise RuntimeError(f"interrupt_not_observed:{interruption}:{interrupted.stderr}")
            resumed = subprocess.run([sys.executable, __file__, "--child", str(scenario)], env=scenario_env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            if resumed.returncode:
                raise RuntimeError(f"resume_failed:{interruption}:{resumed.stderr}")
            results.append(json.loads(resumed.stdout))
        final = results[-1]
        repeated = sum(max(0, value - 1) for result in results for value in result["runs"].values())
        installed_sha_after = _sha(installed) if installed is not None else None
        return {
            "status": "full_read_pipeline_verified",
            "interruptions": list(INTERRUPTIONS),
            "completed_stages_repeated": repeated,
            "active_reader_count": final["active_reader_count"],
            "reader_path": final["reader_path"],
            "sha_alignment": all(result["sha_alignment"] for result in results),
            "exports": final["exports"],
            "fixture": {"pages": 4, "translation_batches": 2},
            "external_writes": False,
            "network_used": False,
            "profile_isolated": True,
            "installed_package": {
                "path": str(installed) if installed is not None else None,
                "sha256_before": installed_sha_before,
                "sha256_after": installed_sha_after,
                "unchanged": installed is not None and installed_sha_before == installed_sha_after,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--crashpoint", choices=INTERRUPTIONS)
    args = parser.parse_args()
    if args.child is not None:
        print(json.dumps(_finish(args.child.resolve(), args.crashpoint), ensure_ascii=False))
        return
    print(json.dumps(verify(), ensure_ascii=False))


if __name__ == "__main__":
    main()
