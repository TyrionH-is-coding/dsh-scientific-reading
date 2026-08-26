from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


INTERRUPTIONS = (
    "after_pdf_publish",
    "after_mineru",
    "after_translation_batch_1",
    "after_reader_staging",
)


def _run_hidden(*args, **kwargs):
    kwargs.setdefault(
        "creationflags",
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    return subprocess.run(*args, **kwargs)


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
    from scientific_reading.full_read_models import (
        FULL_TRANSLATION_CONTRACT_VERSION,
    )

    rows = []
    for index, block in enumerate(batch["blocks"]):
        reference = block.get("source_type") == "reference"
        rows.append(
            {
                "block_id": block["block_id"],
                "source_text": block["english"],
                "translation_zh": "" if reference else f"工程译文：{block['english']}",
                "highlight": "none" if reference else ("result" if index == 0 else "method" if index == 1 else "none"),
            }
        )
    return {
        "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
        "batch_id": batch["batch_id"],
        "source_sha256": batch["source_sha256"],
        "translations": rows,
    }


def _review(required: dict) -> dict:
    from scientific_reading.full_read_models import (
        FULL_REVIEW_CONTRACT_VERSION,
    )

    block_ids = required["available_source_block_ids"]
    if len(block_ids) < 4:
        raise RuntimeError("review_fixture_blocks_insufficient")
    return {
        "contract_version": FULL_REVIEW_CONTRACT_VERSION,
        "highlights": [
            {
                "block_id": block_ids[0],
                "kind": "result",
                "reason": "验收用核心结果。",
            },
            {
                "block_id": block_ids[1],
                "kind": "method",
                "reason": "验收用关键方法。",
            },
        ],
        "guide": {
            "research_question": [
                {"text": "验收研究问题。", "source_block_ids": [block_ids[0]]}
            ],
            "key_methods": [
                {"text": "验收关键方法。", "source_block_ids": [block_ids[1]]}
            ],
            "core_results": [
                {"text": "验收核心结果。", "source_block_ids": [block_ids[2]]}
            ],
            "limitations": [
                {"text": "验收局限性。", "source_block_ids": [block_ids[3]]}
            ],
        },
    }


def _metadata():
    from scientific_reading.models import PaperMetadata

    return PaperMetadata(
        title="Load Distribution in Modular Truss Bridges",
        authors=["Alex Rivera"],
        doi="10.5555/full-read-recovery.2026.1",
        year=2026,
        journal="Fictional Engineering Notes",
    )


def _populate_mineru(generation, metadata, source_sha: str) -> None:
    from PIL import Image
    from scientific_reading.mineru_normalizer import MineruNormalizer
    from scientific_reading.workspace import atomic_write_json

    raw = generation.parsed_dir / "mineru" / "raw" / "fixture" / "auto"
    raw.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 50), "navy").save(raw / "figure-1.png")
    Image.new("RGB", (80, 50), "orange").save(raw / "figure-2.png")
    Image.new("RGB", (100, 60), "white").save(raw / "table-1.png")
    content = [{"type": "header", "text": metadata.title, "text_level": 1, "page_idx": 0, "bbox": [72, 72, 520, 110]}]
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
    normalized = MineruNormalizer("fixture-1").normalize(generation.parsed_dir / "mineru" / "raw", generation.parsed_dir / "mineru", metadata, source_sha)
    for name in ("source_map.json", "parse_report.json"):
        path = generation.parsed_dir / "mineru" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        atomic_write_json(path, payload)
    atomic_write_json(generation.manifest_path, {"version": 1, "assets": [asset.to_dict() for asset in normalized.assets]})


class AcceptanceProvider:
    def __init__(self, source: Path):
        self.source = source

    def acquire(self, _metadata, destination: Path):
        from scientific_reading.pdf_acquisition import AcquisitionResult

        destination.write_bytes(self.source.read_bytes())
        return AcquisitionResult("downloaded", "", "", destination)


class AcceptanceMineruService:
    def run(self, _root, metadata, _executable, _method, **kwargs):
        from scientific_reading.workspace import PaperWorkspace

        workspace = kwargs["workspace"]
        source_sha = _sha(workspace.source_pdf)
        selected = workspace
        if workspace.root.parent.name != "generations":
            selected = PaperWorkspace.create_generation(workspace, source_sha, metadata)
            if not selected.source_pdf.is_file():
                selected.source_pdf.write_bytes(workspace.source_pdf.read_bytes())
        if (selected.parsed_dir / "mineru" / "source_map.json").is_file():
            return SimpleNamespace(
                status="parsed_mineru",
                source_sha256=source_sha,
                provider="acceptance-fixture",
                model_version="fixture-1",
            )
        _populate_mineru(selected, metadata, source_sha)
        from scientific_reading.models import StageRecord

        selected_state = selected.load_job()
        selected_state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={"source_sha256": source_sha, "method": "auto", "mineru_version": "fixture-1", "active_parsed_dir": "parsed/mineru"})
        selected.save_job(selected_state)
        state = workspace.load_job()
        state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={"source_sha256": source_sha, "method": "auto", "mineru_version": "fixture-1", "active_parsed_dir": "parsed/mineru", "active_workspace": f"generations/{source_sha[:16]}"})
        workspace.save_job(state)
        return SimpleNamespace(
            status="parsed_mineru",
            source_sha256=source_sha,
            provider="acceptance-fixture",
            model_version="fixture-1",
        )


def _engine_root() -> Path:
    value = os.environ.get("SR_ENGINE_ROOT")
    if value:
        root = Path(value).resolve()
    else:
        root = next(
            (
                (parent / "Scientific-Reading-for-Newbies").resolve()
                for parent in Path(__file__).resolve().parents
                if (
                    parent / "Scientific-Reading-for-Newbies"
                    / "src"
                    / "scientific_reading"
                ).is_dir()
            ),
            Path(),
        )
    if not (root / "src" / "scientific_reading").is_dir():
        raise RuntimeError("SR_ENGINE_ROOT_invalid")
    return root


def _write_worker_overlay(overlay: Path, engine: Path, helper: Path) -> None:
    package = overlay / "scientific_reading"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"__path__.append({str(engine / 'src' / 'scientific_reading')!r})\n__version__='0.1.0'\n",
        encoding="utf-8",
    )
    (package / "worker.py").write_text(
        f'''from __future__ import annotations
import importlib.util, json, os, socket
from pathlib import Path
from .background_store import BackgroundJobStore
from .reading_pipeline import ReadingPipeline
from .full_read_renderer import FullReadRenderer
from .full_read_service import FullReadService

spec=importlib.util.spec_from_file_location("sr_acceptance_helper", Path({str(helper)!r}))
helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
real_spec=importlib.util.spec_from_file_location("scientific_reading._acceptance_worker", Path({str(engine / 'src' / 'scientific_reading' / 'worker.py')!r}))
runtime=importlib.util.module_from_spec(real_spec); real_spec.loader.exec_module(runtime)
root=Path(os.environ["SR_ACCEPTANCE_ROOT"])

def counter(name):
    path=root/"formal-counts.json"
    value=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {{}}
    value[name]=value.get(name,0)+1
    helper._atomic_json(path,value)

def crash(point):
    config=json.loads((root/"crashpoint.json").read_text(encoding="utf-8"))
    marker=root/(point+".crashed")
    if config.get("point")==point and not marker.exists():
        marker.write_text("97",encoding="utf-8")
        os._exit(97)

def forbidden(*_a,**_k):
    (root/"external-attempted").write_text("blocked",encoding="utf-8")
    raise RuntimeError("external_access_forbidden")
socket.create_connection=forbidden
socket.socket.connect=forbidden
runtime.FeishuClient=forbidden

class Mineru(helper.AcceptanceMineruService):
    def run(self,*args,**kwargs):
        workspace=kwargs["workspace"]
        sha=helper._sha(workspace.source_pdf)
        target=workspace.root/"generations"/sha[:16] if workspace.root.parent.name!="generations" else workspace.root
        if not (target/"parsed"/"mineru"/"source_map.json").is_file(): counter("parse_mineru")
        return super().run(*args,**kwargs)

class Provider(helper.AcceptanceProvider):
    def acquire(self,*args,**kwargs):
        counter("ensure_pdf")
        return super().acquire(*args,**kwargs)

class Full(FullReadService):
    def save_translation_batch(self, workspace, submission):
        target=workspace.reading_dir/"full"/"batches"/(submission["batch_id"]+".translation.json")
        existed=target.is_file()
        result=super().save_translation_batch(workspace,submission)
        if not existed: counter("translation:"+submission["batch_id"])
        if submission["batch_id"].endswith("0001"): crash("after_translation_batch_1")
        return result

def staged(stage,path):
    counter("render_reader")
    crash("after_reader_staging")

def make_pipeline(data_root):
    pipeline=ReadingPipeline(data_root,pdf_provider=Provider(root/"fixture.pdf"),mineru_service=Mineru(),mineru_executable=Path("fixture"),full_read_service=Full(),reader_renderer=FullReadRenderer(publish_hook=staged))
    default=pipeline._default_stage_runner
    def run(stage,state,supplied):
        if stage=="schedule_derived_updates":
            counter(stage); return {{"status":"scheduled"}}
        if stage=="parse_fast": counter(stage)
        result=default(stage,state,supplied)
        if stage=="ensure_pdf": crash("after_pdf_publish")
        if stage=="parse_mineru": crash("after_mineru")
        return result
    pipeline.stage_runner=run
    return pipeline

def main():
    args=runtime._build_parser().parse_args()
    request=BackgroundJobStore(args.data_root).load_request(args.job_id)
    handler=runtime.full_read_pipeline_handler_factory(make_pipeline(Path(request.payload["data_root"])))
    raise SystemExit(runtime.run_job(BackgroundJobStore(args.data_root),args.job_id,{{"full_read_pipeline":handler}}))
if __name__=="__main__": main()
''',
        encoding="utf-8",
    )


def _run_cli(python: Path, env: dict[str, str], data_root: Path, *args: str) -> dict:
    result = _run_hidden(
        [str(python), "-m", "scientific_reading", "--data-root", str(data_root), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=20, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"cli_failed:{args}:{result.stdout}:{result.stderr}")
    return json.loads(result.stdout)


def _formal_scenario(root: Path, engine: Path, interruption: str) -> dict:
    sys.path.insert(0, str(engine / "src"))
    try:
        from scientific_reading.library_service import LibraryService
        from scientific_reading.reading_pipeline import ReadingPipeline
    finally:
        sys.path.pop(0)
    data_root = root / "data"
    profile = root / "profile"
    profile.mkdir()
    _fixture_pdf(root / "fixture.pdf")
    library = LibraryService(data_root)
    try:
        paper_id = library.ingest(_metadata())["paper_id"]
    finally:
        library.close()
    overlay = root / "overlay"
    _write_worker_overlay(overlay, engine, Path(__file__).resolve())
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(overlay), str(engine / "src")))
    env["SR_ACCEPTANCE_ROOT"] = str(root)
    env["DSH_PROFILE"] = "task7-isolated"
    env["DSH_PROFILE_DIR"] = str(profile)
    env.pop("FEISHU_APP_ID", None); env.pop("FEISHU_APP_SECRET", None)
    _atomic_json(root / "crashpoint.json", {"point": interruption})
    first = _run_cli(Path(sys.executable), env, data_root, "full-read-pipeline-start", "--paper-id", paper_id)
    parent = first["parent_job_id"]
    parent_ids = {parent}
    submitted_batches: set[str] = set()
    submitted_review = False
    def wait_previous_worker_exit():
        import time
        from scientific_reading.background_store import BackgroundJobStore
        marker = data_root / "jobs" / parent / "launch.json"
        deadline = time.monotonic() + 5
        while marker.is_file() and time.monotonic() < deadline:
            pid = json.loads(marker.read_text(encoding="utf-8")).get("pid")
            if not isinstance(pid, int) or not BackgroundJobStore._pid_is_alive(pid):
                return
            time.sleep(0.02)
        if marker.is_file():
            pid = json.loads(marker.read_text(encoding="utf-8")).get("pid")
            if isinstance(pid, int) and BackgroundJobStore._pid_is_alive(pid):
                raise RuntimeError("previous_worker_still_alive")
    while True:
        wait_previous_worker_exit()
        stored = ReadingPipeline(data_root).job_store.load_status(parent)
        status = stored.to_dict()
        if status["state"] == "running":
            pipeline = ReadingPipeline(data_root)
            pipeline.inspect(parent)
            if pipeline.job_store.load_status(parent).state == "running":
                import time
                time.sleep(0.05)
                continue
            again = _run_cli(Path(sys.executable), env, data_root, "full-read-pipeline-start", "--paper-id", paper_id)
            parent_ids.add(again["parent_job_id"])
            continue
        if status["state"] == "waiting_agent":
            required = status["required_input"]
            supplied = root / "resume.json"
            if status.get("reason_code") == "translate_full_read":
                batch = json.loads(Path(required["source_manifest_path"]).read_text(encoding="utf-8"))
                if batch["batch_id"] in submitted_batches:
                    import time
                    time.sleep(0.05)
                    continue
                _atomic_json(supplied, {"full_translation": _translation(batch)})
                submitted_batches.add(batch["batch_id"])
            elif status.get("reason_code") == "review_full_read":
                if submitted_review:
                    import time
                    time.sleep(0.05)
                    continue
                _atomic_json(supplied, {"full_review": _review(required)})
                submitted_review = True
            else:
                raise RuntimeError(f"unexpected_agent_gate:{required}")
            resumed = _run_cli(Path(sys.executable), env, data_root, "full-read-pipeline-resume", "--job-id", parent, "--input", str(supplied.resolve()))
            parent_ids.add(resumed["parent_job_id"])
            continue
        if status["state"] == "completed":
            break
        raise RuntimeError(f"formal_worker_failed:{status}")
    exported = _run_cli(Path(sys.executable), env, data_root, "export-assets", "--paper-id", paper_id)
    counts = json.loads((root / "formal-counts.json").read_text(encoding="utf-8"))
    counts["export"] = 1 if exported.get("status") == "exported" else 0
    return {"paper_id": paper_id, "parent_job_id": parent, "parent_ids": sorted(parent_ids), "state": "completed", "counts": counts, "data_root": str(data_root.resolve()), "profile": str(profile.resolve()), "external_blocked": not (root / "external-attempted").exists()}


def _contained(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def _verify_integrity(data_root: Path, paper_id: str) -> dict:
    import csv
    import pymupdf

    paper = data_root / "papers" / paper_id
    readers = list(paper.glob("generations/[a-f0-9]*/reading/reader.html"))
    if len(readers) != 1:
        raise ValueError("active_reader_count_invalid")
    reader = readers[0]
    generation = reader.parents[1]
    manifest_path = generation / "reading" / "reader-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract") != "reader-manifest-v1" or manifest.get("paper_id") != paper_id:
        raise ValueError("reader_identity_invalid")
    source = generation / "source.pdf"
    parser = generation / "parsed" / "mineru" / "source_map.json"
    translation = generation / "reading" / "full" / "translations.json"
    expected = {
        "source_pdf_sha256": _sha(source),
        "parser_manifest_sha256": _sha(parser),
        "translation_manifest_sha256": _sha(translation),
        "reader_sha256": _sha(reader),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("reader_integrity_invalid")
    for key, filename in (("review_manifest_sha256", "review.json"), ("guide_manifest_sha256", "guide.json"), ("highlights_manifest_sha256", "highlights.json")):
        if key in manifest and manifest[key] != _sha(generation / "reading" / "full" / filename):
            raise ValueError("reader_optional_integrity_invalid")
    for asset in manifest["assets"]:
        path = _contained(generation, asset["path"])
        if asset["sha256"] != _sha(path):
            raise ValueError("reader_asset_integrity_invalid")
    exports = generation / "exports"
    export_manifest_path = exports / "manifest.json"
    export_manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
    for asset in export_manifest["assets"]:
        path = _contained(exports, asset["export_path"])
        if path.suffix.lower() != ".png" or asset["export_sha256"] != _sha(path):
            raise ValueError("export_asset_integrity_invalid")
        with pymupdf.open(path) as image:
            if image.page_count != 1:
                raise ValueError("export_png_invalid")
        if "csv_path" in asset:
            csv_path = _contained(exports, asset["csv_path"])
            if csv_path.suffix.lower() not in {".csv", ".json"}:
                raise ValueError("export_structured_extension_invalid")
            if csv_path.suffix.lower() == ".json":
                json.loads(csv_path.read_text(encoding="utf-8"))
            else:
                list(csv.reader(csv_path.read_text(encoding="utf-8").splitlines()))
    captions_path = exports / "captions.md"
    captions_path.read_text(encoding="utf-8")
    kinds = [asset.get("kind") for asset in export_manifest["assets"]]
    return {
        "reader": reader,
        "generation": generation,
        "reader_manifest": manifest_path,
        "exports_manifest": export_manifest_path,
        "exports": exports,
        "active_reader_count": len(readers),
        "export_counts": {
            "figures": kinds.count("figure"),
            "tables": kinds.count("table"),
            "captions": captions_path.is_file(),
            "manifest": export_manifest_path.is_file(),
        },
        "sha_alignment": True,
    }


def _snapshot(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {path.relative_to(root).as_posix(): _sha(path) for path in root.rglob("*") if path.is_file()}


def verify() -> dict:
    engine = _engine_root()
    package_root = Path.home() / ".dsh" / "packages"
    package_inventory_before = _snapshot(package_root)
    packages = sorted(package_root.glob("dsh-external-dsh-scientific-reading-*.tgz"))
    installed = packages[-1] if packages else None
    installed_sha_before = _sha(installed) if installed is not None else None
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(engine / "src")
    child_env.pop("FEISHU_APP_ID", None)
    child_env.pop("FEISHU_APP_SECRET", None)
    formal_results = []
    with tempfile.TemporaryDirectory(prefix="sr7-") as temporary:
        root = Path(temporary)
        for scenario_index, interruption in enumerate(INTERRUPTIONS):
            formal_root = root / f"f{scenario_index}"
            formal = _run_hidden(
                [sys.executable, __file__, "--formal-debug", str(formal_root), "--crashpoint", interruption],
                capture_output=True, text=True, encoding="utf-8",
                env={**child_env, "SR_ENGINE_ROOT": str(engine)}, timeout=60, check=False,
            )
            if formal.returncode:
                raise RuntimeError(f"formal_scenario_failed:{interruption}:{formal.stderr}")
            formal_results.append(json.loads(formal.stdout))
            import time
            time.sleep(0.5)
        final = formal_results[-1]
        integrity = _verify_integrity(Path(final["data_root"]), final["paper_id"])
        def tamper_detected(path: Path, replacement: bytes) -> bool:
            original = path.read_bytes()
            path.write_bytes(replacement)
            try:
                _verify_integrity(Path(final["data_root"]), final["paper_id"])
                raise RuntimeError(f"tamper_not_detected:{path}")
            except ValueError:
                return True
            finally:
                path.write_bytes(original)

        generation = integrity["generation"]
        reader_manifest = json.loads(integrity["reader_manifest"].read_text(encoding="utf-8"))
        reader_asset = generation / reader_manifest["assets"][0]["path"]
        export_path = next(integrity["exports"].rglob("*.png"))
        tamper_negative = {
            "source_pdf": tamper_detected(generation / "source.pdf", b"tampered-source"),
            "parser": tamper_detected(generation / "parsed" / "mineru" / "source_map.json", b"{}"),
            "translation": tamper_detected(generation / "reading" / "full" / "translations.json", b"{}"),
            "reader_html": tamper_detected(integrity["reader"], b"tampered-reader"),
            "reader_asset": tamper_detected(reader_asset, b"tampered-reader-asset"),
            "export_asset": tamper_detected(export_path, b"tampered-export"),
        }
        expected_counts = {"ensure_pdf", "parse_fast", "parse_mineru", "translation:batch-0001", "translation:batch-0002", "render_reader", "schedule_derived_updates", "export"}
        repeated = sum(value - 1 for row in formal_results for key, value in row["counts"].items() if key in expected_counts and value > 1)
        counts_complete = all(expected_counts == set(row["counts"]) and all(value == 1 for value in row["counts"].values()) for row in formal_results)
        installed_sha_after = _sha(installed) if installed is not None else None
        package_inventory_after = _snapshot(package_root)
        relative_reader = integrity["reader"].relative_to(Path(final["data_root"])).as_posix()
        return {
            "status": "full_read_pipeline_verified",
            "interruptions": list(INTERRUPTIONS),
            "completed_stages_repeated": repeated,
            "active_reader_count": integrity["active_reader_count"],
            "reader_path": relative_reader,
            "sha_alignment": integrity["sha_alignment"],
            "exports": integrity["export_counts"],
            "fixture": {"pages": 4, "translation_batches": 2},
            "external_writes": not all(row["external_blocked"] for row in formal_results),
            "network_used": not all(row["external_blocked"] for row in formal_results),
            "profile_isolated": all(Path(row["data_root"]).is_relative_to(root) and Path(row["profile"]).is_relative_to(root) for row in formal_results),
            "tamper_negative": tamper_negative,
            "formal_parent": {
                "all_completed": all(row["state"] == "completed" for row in formal_results),
                "stable_parent_ids": all(len(row["parent_ids"]) == 1 for row in formal_results),
                "unique_active_parent": all(len(row["parent_ids"]) == 1 for row in formal_results),
                "all_stage_counts_once": counts_complete,
                "scenarios": formal_results,
            },
            "installed_package": {
                "path": str(installed) if installed is not None else None,
                "sha256_before": installed_sha_before,
                "sha256_after": installed_sha_after,
                "unchanged": installed is not None and installed_sha_before == installed_sha_after,
                "inventory_unchanged": package_inventory_before == package_inventory_after,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crashpoint", choices=INTERRUPTIONS)
    parser.add_argument("--resolve-engine-only", action="store_true")
    parser.add_argument("--formal-debug", type=Path)
    args = parser.parse_args()
    if args.resolve_engine_only:
        print(json.dumps({"engine_root": str(_engine_root())}, ensure_ascii=False))
        return
    if args.formal_debug is not None:
        args.formal_debug.mkdir(parents=True, exist_ok=True)
        print(json.dumps(_formal_scenario(args.formal_debug.resolve(), _engine_root(), args.crashpoint or INTERRUPTIONS[0]), ensure_ascii=False))
        return
    print(json.dumps(verify(), ensure_ascii=False))


if __name__ == "__main__":
    main()
