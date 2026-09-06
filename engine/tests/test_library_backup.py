import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scientific_reading import __version__
from scientific_reading.__main__ import _resolve_artifact
from scientific_reading.background_store import BackgroundJobStore
from scientific_reading.library_backup import backup_library, restore_library
from scientific_reading.library_service import LibraryService
from scientific_reading.review_service import ReviewService
from scripts.reading_asset_fixture import seed_reading_assets


def _hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def test_backup_restores_relations_generations_reader_and_unfinished_jobs(tmp_path):
    source, restored = tmp_path / "source", tmp_path / "restored"
    sample = seed_reading_assets(source)
    empty_directory = source / "papers" / sample["paper_id"] / "空目录"
    empty_directory.mkdir()
    (source / "secrets").mkdir()
    (source / "secrets/mineru-api-key.dpapi").write_bytes(b"synthetic encrypted credential; never archived")
    (source / ".uploads").mkdir()
    (source / ".uploads/incomplete.pdf").write_bytes(b"unfinished")
    before = _hashes(source)
    archive = tmp_path / "library.zip"
    saved = backup_library(source, archive)
    with zipfile.ZipFile(archive) as packaged:
        assert json.loads(packaged.read("manifest.json"))["engine_version"] == __version__
    result = restore_library(archive, restored)
    assert saved["status"] == result["status"] == "completed"
    assert _hashes(source) == before
    assert not (restored / "secrets").exists()
    assert not (restored / ".uploads").exists()
    assert (restored / empty_directory.relative_to(source)).is_dir()
    library = LibraryService(restored)
    try:
        item = library.get_item(sample["paper_id"])
        assert item["status"] == "full_read_ready"
        fields = library.conn.execute("SELECT personal_thoughts, understanding_level, user_notes, folder_id FROM items WHERE paper_id=?", (sample["paper_id"],)).fetchone()
        assert tuple(fields) == ("关联尚需验证", "部分理解", "核对分母 n=12", sample["folder_id"])
        assert {r[0] for r in library.conn.execute("SELECT tag FROM item_tags")} == {"抗磷脂", "已读"}
    finally:
        library.close()
    review = ReviewService(restored)
    try:
        assert review.context_for_session("fixture-review")["confirmed_conclusions"][0]["evidence_locator"] == "旧定位：结果部分"
    finally:
        review.close()
    resolved = _resolve_artifact(restored, sample["paper_id"], "reader")
    reader = restored / "papers" / sample["paper_id"] / resolved["rel_path"]
    assert reader.read_bytes() == (source / sample["reader"]).read_bytes()
    for generation in sample["generations"]:
        original, recovered = _hashes(source / generation), _hashes(restored / generation)
        assert {k: v for k, v in original.items() if k != "job.json" and not k.endswith(".lock")} == {k: v for k, v in recovered.items() if k != "job.json" and not k.endswith(".lock")}
        job = json.loads((restored / generation / "job.json").read_text(encoding="utf-8"))
        full = job["stages"]["full_read"]
        assert full["status"] == "completed"
        assert Path(full["result"]["reading_guide_json"]).is_relative_to(restored)
    jobs = BackgroundJobStore(restored)
    status = jobs.load_status(sample["job_id"])
    assert status.state == "interrupted" and status.pid is None
    assert status.error == "restored_requires_resume"
    assert jobs.load_request(sample["job_id"]).payload["data_root"] == str(restored)
    assert not (jobs.handle(sample["job_id"]).root / "launch.json").exists()
    downloads = json.loads((restored / "jobs/downloads/job_1234567890abcdef.json").read_text())
    assert downloads["status"] == "failed" and downloads["owner_pid"] is None


@pytest.fixture
def backed_up(tmp_path):
    source = tmp_path / "source"
    library = LibraryService(source)
    library.close()
    archive = tmp_path / "library.zip"
    backup_library(source, archive)
    return archive


def _alter_archive(original, changed, transform):
    with zipfile.ZipFile(original) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    transform(entries)
    with zipfile.ZipFile(changed, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


@pytest.mark.parametrize("change", ["tamper", "missing", "traversal", "version", "engine_version", "schema", "extra", "directory_collision", "directory_traversal"])
def test_invalid_archive_never_publishes_a_partial_library(backed_up, tmp_path, change):
    def transform(entries):
        manifest = json.loads(entries["manifest.json"])
        if change == "tamper": entries["data/library.sqlite"] = b"tampered"
        elif change == "missing": del entries["data/library.sqlite"]
        elif change == "traversal": manifest["files"][0]["path"] = "../escaped"
        elif change == "version": manifest["version"] = 999
        elif change == "engine_version": del manifest["engine_version"]
        elif change == "schema": manifest["schema_version"] = 999
        elif change == "extra": entries["data/unlisted.txt"] = b"extra"
        elif change == "directory_collision": manifest["directories"] = ["library.sqlite"]
        elif change == "directory_traversal": manifest["directories"] = ["../outside"]
        entries["manifest.json"] = json.dumps(manifest).encode()
    changed = tmp_path / "invalid.zip"
    _alter_archive(backed_up, changed, transform)
    destination = tmp_path / "new"
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        restore_library(changed, destination)
    assert not destination.exists()
    assert not (tmp_path / "escaped").exists()


def test_nonempty_target_and_existing_backup_are_preserved(backed_up, tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "notes.txt").write_text("用户笔记", encoding="utf-8")
    before = _hashes(target)
    with pytest.raises(ValueError, match="restore_target_not_empty"):
        restore_library(backed_up, target)
    assert _hashes(target) == before
    previous = backed_up.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        backup_library(tmp_path / "source", backed_up)
    assert backed_up.read_bytes() == previous


def test_restore_interruption_leaves_existing_empty_target_empty(backed_up, tmp_path, monkeypatch):
    from scientific_reading import library_backup
    target = tmp_path / "empty"
    target.mkdir()
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(library_backup, "_recover_tasks", interrupted)
    with pytest.raises(KeyboardInterrupt):
        restore_library(backed_up, target)
    assert target.is_dir() and list(target.iterdir()) == []


def test_publish_failure_preserves_existing_empty_target(backed_up, tmp_path, monkeypatch):
    target = tmp_path / "empty"
    target.mkdir()
    rename = Path.rename
    def fail_publish(path, destination):
        if path.name.startswith(".sr-restore-"):
            raise OSError("injected publication failure")
        return rename(path, destination)
    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(OSError, match="injected"):
        restore_library(backed_up, target)
    assert target.is_dir() and not list(target.iterdir())


def test_archive_change_during_restore_aborts_before_publish(backed_up, tmp_path, monkeypatch):
    from scientific_reading import library_backup
    original = library_backup._recover_tasks

    def mutate_after_extract(*args, **kwargs):
        result = original(*args, **kwargs)
        with backed_up.open("ab") as stream:
            stream.write(b"changed-after-extract")
        return result

    monkeypatch.setattr(library_backup, "_recover_tasks", mutate_after_extract)
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="backup_archive_changed"):
        restore_library(backed_up, target)
    assert not target.exists()


@pytest.mark.parametrize("state", ["waiting_agent", "waiting_user", "failed", "completed"])
def test_all_task_states_rebase_execution_paths_without_changing_state(tmp_path, state):
    from scientific_reading.background_models import BackgroundRequest
    source, target = tmp_path / "source", tmp_path / "restored"
    library = LibraryService(source)
    library.close()
    jobs = BackgroundJobStore(source)
    handle = jobs.create_or_get(BackgroundRequest("sample", "full_read", "2" * 64, {"data_root": str(source)}))
    jobs.transition(handle.root.name, "running", pid=99999999)
    values = {"output_dir": str(source / "papers/sample/reading")}
    jobs.transition(handle.root.name, state, reason_code="review_full_read" if state.startswith("waiting") else None, required_input=values, result=values)
    jobs.save_resume_input(handle.root.name, values)
    (handle.root / "reading_pipeline.json").write_text(json.dumps({"state": state, "stage_outputs": {"render_reader": values}}), encoding="utf-8")
    archive = tmp_path / "snapshot.zip"
    backup_library(source, archive)
    restore_library(archive, target)
    restored_jobs = BackgroundJobStore(target)
    restored_state = restored_jobs.load_status(handle.root.name)
    assert restored_state.state == state
    for container in (restored_state.required_input, restored_state.result, restored_jobs.load_resume_input(handle.root.name)):
        assert Path(container["output_dir"]) == target / "papers/sample/reading"
    pipeline = json.loads((restored_jobs.handle(handle.root.name).root / "reading_pipeline.json").read_text())
    assert Path(pipeline["stage_outputs"]["render_reader"]["output_dir"]).is_relative_to(target)


def test_external_asset_change_aborts_snapshot_without_reverting_new_content(backed_up, tmp_path, monkeypatch):
    from scientific_reading import library_backup
    source = tmp_path / "source"
    note = source / "notes.txt"
    note.write_text("before")
    original = library_backup._inventory
    calls = 0
    def inventory(root):
        nonlocal calls
        result = original(root)
        calls += 1
        if calls == 1:
            note.write_text("external update")
        return result
    monkeypatch.setattr(library_backup, "_inventory", inventory)
    output = tmp_path / "unstable.zip"
    with pytest.raises(ValueError, match="backup_assets_changed"):
        backup_library(source, output)
    assert not output.exists() and note.read_text() == "external update"


def test_artifact_version_matches_the_bytes_recorded_in_the_archive(tmp_path, monkeypatch):
    source = tmp_path / "source"
    library = LibraryService(source)
    library.close()
    artifact = source / "papers" / "sample" / "manifest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({"contract": "fixture", "version": 1}))
    original_read_text = Path.read_text
    raced = False

    def transient_read(path, *args, **kwargs):
        nonlocal raced
        if path == artifact and not raced:
            raced = True
            original = path.read_bytes()
            path.write_text(json.dumps({"contract": "fixture", "version": 2}))
            try:
                return original_read_text(path, *args, **kwargs)
            finally:
                path.write_bytes(original)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read)
    archive = tmp_path / "snapshot.zip"
    backup_library(source, archive)
    with zipfile.ZipFile(archive) as saved:
        manifest = json.loads(saved.read("manifest.json"))
        archived = json.loads(saved.read("data/papers/sample/manifest.json"))
    assert manifest["artifact_versions"]["papers/sample/manifest.json"] == {
        "contract": archived["contract"],
        "version": archived["version"],
    }


def test_resource_limits_reject_before_restore(backed_up, tmp_path, monkeypatch):
    from scientific_reading import library_backup
    monkeypatch.setattr(library_backup, "MAX_FILE_BYTES", 64)
    with pytest.raises(ValueError, match="backup_resource_limit"):
        restore_library(backed_up, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_excluded_paths_are_case_insensitive_for_backup_and_restore(tmp_path):
    source = tmp_path / "source"
    library = LibraryService(source)
    library.close()
    secret = source / "SeCrEtS" / "mineru-api-key.dpapi"
    secret.parent.mkdir()
    secret.write_bytes(b"synthetic credential")
    archive = tmp_path / "snapshot.zip"
    backup_library(source, archive)
    with zipfile.ZipFile(archive) as saved:
        assert not any(name.casefold().startswith("data/secrets/") for name in saved.namelist())

    def add_mixed_case_secret(entries):
        payload = b"must not restore"
        relative = "SeCrEtS/injected.dpapi"
        manifest = json.loads(entries["manifest.json"])
        manifest["files"].append(
            {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
        entries["data/" + relative] = payload
        entries["manifest.json"] = json.dumps(manifest).encode()

    hostile = tmp_path / "hostile.zip"
    _alter_archive(archive, hostile, add_mixed_case_secret)
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="backup_manifest_path_invalid"):
        restore_library(hostile, target)
    assert not target.exists()
