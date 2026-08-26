from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .identifiers import metadata_identity_compatible, stable_paper_id
from .models import JobState, PaperMetadata


def _validate_paper_id(paper_id: str) -> None:
    if (
        not isinstance(paper_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id)
        or ".." in paper_id
    ):
        raise ValueError("paper_id_invalid")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(frozen=True, slots=True)
class PaperWorkspace:
    root: Path

    @classmethod
    def create(cls, data_root: Path, metadata: PaperMetadata) -> PaperWorkspace:
        return cls._initialize(
            Path(data_root).resolve() / "papers" / stable_paper_id(metadata),
            metadata,
        )

    @classmethod
    def create_for_paper_id(
        cls, data_root: Path, paper_id: str, metadata: PaperMetadata
    ) -> PaperWorkspace:
        """按已验证的 SQLite paper_id 建立工作目录，不重新推导身份。"""
        _validate_paper_id(paper_id)
        return cls._initialize(
            Path(data_root).resolve() / "papers" / paper_id,
            metadata,
        )

    @classmethod
    def create_generation(
        cls,
        workspace: PaperWorkspace,
        source_sha256: str,
        metadata: PaperMetadata,
    ) -> PaperWorkspace:
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise ValueError("source_sha256_invalid")
        return cls._initialize(
            workspace.root / "generations" / source_sha256[:16],
            metadata,
        )

    @classmethod
    def _initialize(cls, root: Path, metadata: PaperMetadata) -> PaperWorkspace:
        workspace = cls(root=root)
        for directory in (
            workspace.parsed_images,
            workspace.parsed_tables,
            workspace.reading_dir,
            workspace.output_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        if not workspace.metadata_path.exists():
            atomic_write_json(workspace.metadata_path, metadata.to_dict())
        if not workspace.job_path.exists():
            workspace.save_job(JobState(paper_id=root.name))
        return workspace

    @property
    def metadata_path(self) -> Path:
        return self.root / "metadata.json"

    @property
    def job_path(self) -> Path:
        return self.root / "job.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def source_pdf(self) -> Path:
        return self.root / "source.pdf"

    @property
    def parsed_dir(self) -> Path:
        return self.root / "parsed"

    @property
    def parsed_images(self) -> Path:
        return self.parsed_dir / "images"

    @property
    def parsed_tables(self) -> Path:
        return self.parsed_dir / "tables"

    @property
    def reading_dir(self) -> Path:
        return self.root / "reading"

    @property
    def reader_html(self) -> Path:
        return self.reading_dir / "reader.html"

    @property
    def reader_manifest(self) -> Path:
        return self.reading_dir / "reader-manifest.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def exports_figures(self) -> Path:
        return self.exports_dir / "figures"

    @property
    def exports_tables(self) -> Path:
        return self.exports_dir / "tables"

    @property
    def exports_captions(self) -> Path:
        return self.exports_dir / "captions.md"

    @property
    def exports_manifest(self) -> Path:
        return self.exports_dir / "manifest.json"

    def existing_reader_html(self) -> Path | None:
        for candidate in (
            self.reader_html,
            self.reading_dir / "reader_full.html",
            self.output_dir / "reader.html",
            self.output_dir / "reader_full.html",
            self.root / "reader.html",
            self.root / "reader_full.html",
        ):
            if candidate.is_file():
                return candidate
        return None

    def save_job(self, state: JobState) -> None:
        if state.paper_id != self.root.name:
            raise ValueError("job state paper_id 与工作目录不一致")
        atomic_write_json(self.job_path, state.to_dict())

    def load_job(self) -> JobState:
        value = json.loads(self.job_path.read_text(encoding="utf-8"))
        return JobState.from_dict(value)

def validate_explicit_workspace(
    data_root: Path,
    paper_id: str,
    metadata: PaperMetadata,
    workspace: PaperWorkspace,
) -> None:
    _validate_paper_id(paper_id)
    base = (Path(data_root).resolve() / "papers" / paper_id).resolve()
    root = workspace.root.resolve()
    generation_root = base / "generations"
    is_base = root == base
    is_generation = (
        root.parent == generation_root
        and re.fullmatch(r"[0-9a-f]{16}", root.name) is not None
    )
    if not (is_base or is_generation):
        raise ValueError("workspace_paper_id_mismatch")
    try:
        stored_metadata = PaperMetadata.from_dict(
            json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        )
        state = workspace.load_job()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("workspace_identity_invalid") from error
    if not metadata_identity_compatible(stored_metadata, metadata):
        raise ValueError("workspace_metadata_mismatch")
    expected_job_id = root.name if is_generation else paper_id
    if state.paper_id != expected_job_id:
        raise ValueError("workspace_paper_id_mismatch")
