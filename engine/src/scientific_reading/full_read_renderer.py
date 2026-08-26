from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from bs4 import BeautifulSoup
from latex2mathml.converter import convert as latex_to_mathml

from reader.build_reader import (
    READER_BUILD_VERSION,
    build_reader,
    normalize_highlight_kind,
)

from .full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
    FullReviewSubmission,
    Translation,
)
from .models import AssetRecord, PaperMetadata
from .parse_models import SourceBlock
from .workspace import PaperWorkspace
from .package_manifest import refresh_generation_package_manifest


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


_MATH_PATTERN = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\$(.+?)(?<!\\)\$",
    re.DOTALL,
)


def _render_rich_text(value: object) -> str:
    source = str(value)
    rendered: list[str] = []
    position = 0
    for match in _MATH_PATTERN.finditer(source):
        rendered.append(_escape(source[position:match.start()]))
        latex = match.group(1) if match.group(1) is not None else match.group(2)
        display = "block" if match.group(1) is not None else "inline"
        try:
            rendered.append(latex_to_mathml(latex.strip(), display=display))
        except (TypeError, ValueError):
            rendered.append(_escape(match.group(0)))
        position = match.end()
    rendered.append(_escape(source[position:]))
    return "".join(rendered)


def _append_rich_text(target, value: object) -> None:
    fragment = BeautifulSoup(_render_rich_text(value), "html.parser")
    for child in list(fragment.contents):
        target.append(child)


class FullReadRenderer:
    def __init__(self, *, publish_hook: Callable[[str, Path], None] | None = None):
        self._publish_hook = publish_hook

    def render_completed(
        self,
        workspace: PaperWorkspace,
        *,
        paper_id: str,
    ) -> dict[str, str]:
        with self._publish_claim(workspace):
            return self._render_completed(workspace, paper_id=paper_id)

    def _render_completed(
        self,
        workspace: PaperWorkspace,
        *,
        paper_id: str,
    ) -> dict[str, str]:
        from .full_read_service import FullReadError, FullReadService

        translation_path = workspace.reading_dir / "full" / "translations.json"
        guide_path = workspace.reading_dir / "full" / "reading_guide.json"
        highlights_path = workspace.reading_dir / "full" / "highlights.json"
        try:
            payload = json.loads(translation_path.read_text(encoding="utf-8"))
            active = FullReadService._inspect_active_mineru(workspace)
            if set(payload) != {"contract_version", "source_sha256", "translations"}:
                raise ValueError("unexpected_keys")
            if payload["contract_version"] != FULL_TRANSLATION_CONTRACT_VERSION:
                raise ValueError("translation_contract_invalid")
            if payload["source_sha256"] != active.source_sha256:
                raise ValueError("translation_source_sha_mismatch")
            rows = payload["translations"]
            if not isinstance(rows, list) or len(rows) != len(active.rows):
                raise ValueError("translation_block_order_mismatch")
            parsed = tuple(
                Translation.from_dict(
                    row,
                    expected_source_text=source["english"],
                    reference=source["source_type"] == "reference",
                )
                for row, source in zip(rows, active.rows, strict=True)
            )
            if tuple(item.block_id for item in parsed) != tuple(
                source["block_id"] for source in active.rows
            ):
                raise ValueError("translation_block_order_mismatch")
            translations = {item.block_id: item for item in parsed}
            _trusted_active, trusted = FullReadService()._collect_translations(
                workspace
            )
            if translations != trusted:
                raise ValueError("translation_manifest_batch_mismatch")
            state = workspace.load_job()
            stage = state.stages.get("full_read")
            if stage is None or stage.status != "completed":
                raise ValueError("full_review_not_completed")
            stage_result = stage.result
            reader_revision = stage_result.get("reader_revision")
            reader_build_version = stage_result.get(
                "reader_build_version"
            )
            review_value = stage_result.get("review")
            if (
                not isinstance(reader_revision, str)
                or re.fullmatch(r"[0-9a-f]{64}", reader_revision) is None
                or reader_build_version != READER_BUILD_VERSION
                or not isinstance(review_value, dict)
            ):
                raise ValueError("full_review_identity_invalid")
            substantive_ids = {
                row["block_id"]
                for row in active.rows
                if row["source_type"] not in {"header", "reference"}
            }
            review = FullReviewSubmission.from_dict(
                review_value,
                available_block_ids=substantive_ids,
                substantive_block_count=len(substantive_ids),
            )
            if review.to_dict() != review_value:
                raise ValueError("full_review_manifest_mismatch")
            guide_payload = json.loads(guide_path.read_text(encoding="utf-8"))
            if guide_payload != {
                "contract_version": FULL_REVIEW_CONTRACT_VERSION,
                "reader_revision": reader_revision,
                "guide": review_value["guide"],
            }:
                raise ValueError("reading_guide_manifest_mismatch")
            expected_highlights = {
                item.block_id: (item.highlight, "全文翻译标注")
                for item in translations.values()
                if item.highlight != "none"
            }
            for item in review.highlights:
                expected_highlights.setdefault(
                    item.block_id,
                    (item.kind, item.reason),
                )
            expected_highlight_payload = {
                "contract_version": FULL_REVIEW_CONTRACT_VERSION,
                "highlights": [
                    {
                        "block_id": block_id,
                        "kind": kind,
                        "reason": reason,
                    }
                    for block_id, (kind, reason) in expected_highlights.items()
                ],
            }
            highlight_payload = json.loads(
                highlights_path.read_text(encoding="utf-8")
            )
            if highlight_payload != expected_highlight_payload:
                raise ValueError("highlight_manifest_mismatch")
            highlights = expected_highlights
        except (
            OSError, KeyError, TypeError, ValueError, json.JSONDecodeError,
            FullReadError,
        ) as error:
            raise ValueError("translation_manifest_invalid") from error
        metadata, blocks, assets = self._load_active(workspace)
        block_ids = {block.block_id for block in blocks}
        body = {key: value for key, value in translations.items() if key in block_ids}
        if tuple(body) != tuple(block.block_id for block in blocks):
            raise ValueError("translation_block_mismatch")
        caption_links = self._caption_links(workspace, assets, translations)
        parser_path = workspace.parsed_dir / "mineru" / "source_map.json"
        source_sha = workspace.load_job().stages["paper_parse_upgrade"].result[
            "source_sha256"
        ]
        for abandoned in workspace.reading_dir.glob(".reader-publish-*"):
            if abandoned.is_symlink() or not abandoned.is_dir():
                continue
            staged_html = abandoned / "reader.html"
            staged_manifest = abandoned / "reader-manifest.json"
            try:
                self._validate_staged_reader(staged_html, staged_manifest)
                staged = json.loads(staged_manifest.read_text(encoding="utf-8"))
                recoverable = self._staging_matches_current_inputs(
                    workspace,
                    staged,
                    paper_id=paper_id,
                    source_sha=source_sha,
                    parser_path=parser_path,
                    translation_path=translation_path,
                    assets=assets,
                    caption_links=caption_links,
                )
            except (OSError, ValueError, json.JSONDecodeError):
                recoverable = False
            if recoverable:
                workspace.reader_html.parent.mkdir(parents=True, exist_ok=True)
                staged_html.replace(workspace.reader_html)
                staged_manifest.replace(workspace.reader_manifest)
                shutil.rmtree(abandoned)
                self._validate_staged_reader(
                    workspace.reader_html, workspace.reader_manifest
                )
                refresh_generation_package_manifest(workspace)
                return self._result(workspace, source_sha)
            shutil.rmtree(abandoned)
        staging = workspace.reading_dir / f".reader-publish-{uuid.uuid4().hex}"
        staging.mkdir()
        staged_html = staging / "reader.html"
        staged_manifest = staging / "reader-manifest.json"
        old_html = workspace.reader_html.read_bytes() if workspace.reader_html.is_file() else None
        old_manifest = workspace.reader_manifest.read_bytes() if workspace.reader_manifest.is_file() else None
        try:
            base_path = staging / "reader.base.html"
            base_path.write_text(
                self._base_html(workspace, metadata, blocks, body, assets, caption_links),
                encoding="utf-8",
                newline="\n",
            )
            build_reader(
                base_path,
                staged_html,
                highlights,
                guide=review.to_dict()["guide"],
                paper_id=paper_id,
                reader_revision=reader_revision,
            )
            reader_sha = self._sha256(staged_html)
            manifest = {
                "contract": "reader-manifest-v1",
                "paper_id": paper_id,
                "source_pdf_sha256": source_sha,
                "parser_manifest_sha256": self._sha256(parser_path),
                "translation_manifest_sha256": self._sha256(translation_path),
                "reading_guide_sha256": self._sha256(guide_path),
                "highlights_manifest_sha256": self._sha256(highlights_path),
                "reader_build_version": reader_build_version,
                "reader_revision": reader_revision,
                "review": review.to_dict(),
                "reader_sha256": reader_sha,
                "generated_at": datetime.now(UTC).isoformat(),
                "source_blocks": [
                    {
                        "block_id": row["block_id"],
                        "page": row["page"],
                        "source_type": row["source_type"],
                        "source_index": (
                            int(row["block_id"].rsplit("c", 1)[1]) - 1
                            if row["source_type"] == "caption"
                            else next(
                                block.source_index for block in blocks
                                if block.block_id == row["block_id"]
                            )
                        ),
                    }
                    for row in active.rows
                ],
                "assets": [
                    {
                        "id": asset.asset_id,
                        "kind": asset.kind,
                        "page": asset.page,
                        "path": asset.relative_path,
                        "sha256": self._sha256(workspace.root / asset.relative_path),
                        "caption_block_id": caption_links[asset.asset_id].block_id
                        if asset.asset_id in caption_links else None,
                    }
                    for asset in assets
                ],
            }
            if old_manifest is not None and old_html is not None:
                try:
                    previous = json.loads(old_manifest)
                except json.JSONDecodeError:
                    previous = {}
                stable_keys = (
                    "contract", "paper_id", "source_pdf_sha256",
                    "parser_manifest_sha256", "translation_manifest_sha256",
                    "reading_guide_sha256", "highlights_manifest_sha256",
                    "reader_build_version", "reader_revision", "review",
                    "reader_sha256", "source_blocks", "assets",
                )
                same_inputs = all(
                    previous.get(key) == manifest[key] for key in stable_keys
                )
                if same_inputs and isinstance(previous.get("generated_at"), str):
                    manifest["generated_at"] = previous["generated_at"]
                try:
                    self._validate_staged_reader(
                        workspace.reader_html, workspace.reader_manifest
                    )
                    existing_valid = True
                except (OSError, ValueError, json.JSONDecodeError):
                    existing_valid = False
                if existing_valid and same_inputs:
                    refresh_generation_package_manifest(workspace)
                    return self._result(workspace, source_sha)
            staged_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self._validate_staged_reader(staged_html, staged_manifest)
            if self._publish_hook is not None:
                self._publish_hook("reader_staged", staging)
            workspace.reader_html.parent.mkdir(parents=True, exist_ok=True)
            staged_html.replace(workspace.reader_html)
            staged_manifest.replace(workspace.reader_manifest)
            self._validate_staged_reader(workspace.reader_html, workspace.reader_manifest)
            refresh_generation_package_manifest(workspace)
        except Exception:
            if old_html is not None:
                workspace.reader_html.write_bytes(old_html)
            elif workspace.reader_html.exists():
                workspace.reader_html.unlink()
            if old_manifest is not None:
                workspace.reader_manifest.write_bytes(old_manifest)
            elif workspace.reader_manifest.exists():
                workspace.reader_manifest.unlink()
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return self._result(workspace, source_sha)

    @classmethod
    def _staging_matches_current_inputs(
        cls,
        workspace: PaperWorkspace,
        staged: dict,
        *,
        paper_id: str,
        source_sha: str,
        parser_path: Path,
        translation_path: Path,
        assets: tuple[AssetRecord, ...],
        caption_links: dict[str, Translation],
    ) -> bool:
        if workspace.source_pdf.is_symlink():
            return False
        expected_assets = []
        for asset in assets:
            path = workspace.root / asset.relative_path
            try:
                path.relative_to(workspace.root)
                resolved = path.resolve(strict=True)
                resolved.relative_to(workspace.root.resolve())
            except (OSError, ValueError):
                return False
            if path.is_symlink() or not path.is_file():
                return False
            expected_assets.append(
                {
                    "id": asset.asset_id,
                    "kind": asset.kind,
                    "page": asset.page,
                    "path": asset.relative_path,
                    "sha256": cls._sha256(path),
                    "caption_block_id": (
                        caption_links[asset.asset_id].block_id
                        if asset.asset_id in caption_links else None
                    ),
                }
            )
        try:
            actual_source_sha = cls._sha256(workspace.source_pdf)
            parser_sha = cls._sha256(parser_path)
            translation_sha = cls._sha256(translation_path)
        except OSError:
            return False
        return (
            staged.get("contract") == "reader-manifest-v1"
            and staged.get("paper_id") == paper_id
            and source_sha == actual_source_sha
            and staged.get("source_pdf_sha256") == actual_source_sha
            and staged.get("parser_manifest_sha256") == parser_sha
            and staged.get("translation_manifest_sha256") == translation_sha
            and staged.get("assets") == expected_assets
        )

    @staticmethod
    @contextmanager
    def _publish_claim(workspace: PaperWorkspace):
        lock_path = workspace.reading_dir / ".reader-publish.lock"
        stream = lock_path.open("a+b")
        if lock_path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + 10.0
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    raise TimeoutError("reader_publish_busy") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    @staticmethod
    def _result(workspace: PaperWorkspace, source_sha: str) -> dict[str, str]:
        manifest = json.loads(
            workspace.reader_manifest.read_text(encoding="utf-8")
        )
        return {
            "status": "reader_ready",
            "reader_html": str(workspace.reader_html),
            "manifest_path": str(workspace.reader_manifest),
            "reader_source_sha256": source_sha,
            "reader_revision": manifest["reader_revision"],
        }

    @classmethod
    def _validate_staged_reader(cls, html_path: Path, manifest_path: Path) -> None:
        rendered = html_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not cls._is_self_contained(rendered):
            raise ValueError("remote_resource_forbidden")
        if manifest.get("reader_sha256") != cls._sha256(html_path):
            raise ValueError("reader_manifest_mismatch")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _caption_links(
        workspace: PaperWorkspace,
        assets: tuple[AssetRecord, ...],
        translations: dict[str, Translation],
    ) -> dict[str, Translation]:
        supplied = {key for key in translations if "-c" in key}
        if not supplied:
            return {}
        candidates = list((workspace.parsed_dir / "mineru" / "raw").rglob("*_content_list.json"))
        if len(candidates) != 1:
            raise ValueError("caption_asset_ambiguous")
        items = json.loads(candidates[0].read_text(encoding="utf-8"))
        by_key: dict[tuple[str, int, int], Translation] = {}
        counts: dict[tuple[str, int], int] = {}
        for index, item in enumerate(items):
            kind = item.get("type")
            if kind not in {"image", "table"}:
                continue
            page = int(item["page_idx"]) + 1
            key = (kind, page)
            counts[key] = counts.get(key, 0) + 1
            prefix = "image" if kind == "image" else "table"
            captions = item.get(f"{prefix}_caption", [])
            text = "\n".join(value.strip() for value in captions if isinstance(value, str) and value.strip())
            if not text:
                continue
            block_id = f"p{page:04d}-c{index + 1:04d}"
            translation = translations.get(block_id)
            if translation is None or translation.source_text != text:
                raise ValueError("caption_asset_ambiguous")
            by_key[(kind, page, counts[key])] = translation
        linked: dict[str, Translation] = {}
        for asset in assets:
            kind = "image" if asset.kind == "figure" else "table"
            match = re.search(r"(?:img|table)([0-9]{4})", asset.asset_id)
            if match is None:
                raise ValueError("caption_asset_ambiguous")
            translation = by_key.get(
                (kind, asset.page, int(match.group(1)))
            )
            if asset.caption and translation is None:
                raise ValueError("caption_asset_ambiguous")
            if translation is not None:
                linked[asset.asset_id] = translation
        caption_ids = {value.block_id for value in linked.values()}
        if supplied != caption_ids:
            raise ValueError("caption_asset_ambiguous")
        return linked

    def render(
        self,
        workspace: PaperWorkspace,
        translations: dict[str, Translation],
        highlights: dict[str, tuple[str, str]],
        output: Path,
        *,
        review: FullReviewSubmission,
        reader_revision: str,
        paper_id: str,
    ) -> Path:
        metadata, blocks, assets = self._load_active(workspace)
        block_ids = tuple(block.block_id for block in blocks)
        body = {
            block_id: translation
            for block_id, translation in translations.items()
            if block_id in set(block_ids)
        }
        if tuple(body) != block_ids:
            raise ValueError("translation_block_mismatch")
        try:
            highlights = {
                block_id: (normalize_highlight_kind(source), reason)
                for block_id, (source, reason) in highlights.items()
            }
        except ValueError as error:
            raise ValueError("highlight_invalid") from error
        if any(not reason.strip() for _source, reason in highlights.values()):
            raise ValueError("highlight_invalid")

        caption_links = self._caption_links(workspace, assets, translations)
        base = self._base_html(
            workspace,
            metadata,
            blocks,
            body,
            assets,
            caption_links,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        base_path = output.with_suffix(".base.html")
        try:
            base_path.write_text(
                base,
                encoding="utf-8",
                newline="\n",
            )
            build_reader(
                base_path,
                output,
                highlights,
                guide=review.to_dict()["guide"],
                paper_id=paper_id,
                reader_revision=reader_revision,
            )
        finally:
            base_path.unlink(missing_ok=True)
        rendered = output.read_text(encoding="utf-8")
        if not self._is_self_contained(rendered):
            output.unlink(missing_ok=True)
            raise ValueError("remote_resource_forbidden")
        return output

    @staticmethod
    def _load_active(
        workspace: PaperWorkspace,
    ) -> tuple[
        PaperMetadata,
        tuple[SourceBlock, ...],
        tuple[AssetRecord, ...],
    ]:
        state = workspace.load_job()
        stage = state.stages.get("paper_parse_upgrade")
        if (
            stage is None
            or stage.status != "completed"
            or stage.result.get("active_parsed_dir")
            != "parsed/mineru"
        ):
            raise ValueError("active_mineru_required")
        root = workspace.parsed_dir / "mineru"
        try:
            metadata = PaperMetadata.from_dict(
                json.loads(
                    workspace.metadata_path.read_text(encoding="utf-8")
                )
            )
            source_map = json.loads(
                (root / "source_map.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (root / "parse_report.json").read_text(encoding="utf-8")
            )
            blocks = tuple(
                SourceBlock.from_dict(value)
                for value in source_map["blocks"]
            )
            assets = tuple(
                AssetRecord.from_dict(value)
                for value in report.get("assets", [])
            )
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError("active_mineru_artifact_invalid") from error
        return metadata, blocks, assets

    def _base_html(
        self,
        workspace: PaperWorkspace,
        metadata: PaperMetadata,
        blocks: tuple[SourceBlock, ...],
        translations: dict[str, Translation],
        assets: tuple[AssetRecord, ...],
        caption_links: dict[str, Translation] | None = None,
    ) -> str:
        levels = self._text_levels(blocks)
        asset_indices = self._asset_source_indices(workspace, assets, blocks)
        pending_assets = sorted(
            self._display_assets(assets),
            key=lambda asset: (asset_indices[asset.asset_id], asset.asset_id),
        )

        toc_rows: list[str] = []
        article_rows = [
            f"<h1>{_escape(metadata.title)}</h1>",
            f'<p class="original-title">{_escape(metadata.title)}</p>',
        ]
        for block in blocks:
            while pending_assets and (
                block.source_index is not None
                and asset_indices[pending_assets[0].asset_id] < block.source_index
            ):
                article_rows.extend(
                    self._render_assets(
                        workspace,
                        [pending_assets.pop(0)],
                        caption_links,
                    )
                )
            translation = translations[block.block_id]
            rendered_text = translation.translation_zh or translation.source_text
            source_type = block.source_type or "text"
            raw_level = levels.get(block.block_id)
            is_heading = (
                (
                    raw_level is not None
                    or (
                        source_type == "header"
                        and block.structure_source
                        != "outline_noise_filtered"
                    )
                )
            ) and block.text.strip() != metadata.title.strip() and sum(
                character.isalpha() for character in block.text
            ) >= 2
            if is_heading:
                level = min(6, (raw_level + 1) if raw_level else 2)
                section_id = f"section-{block.block_id}"
                article_rows.append(
                    f'<h{level} id="{section_id}">'
                    f"{_render_rich_text(rendered_text)}</h{level}>"
                )
                toc_rows.append(
                    f'<li class="toc-h{level}"><a href="#{section_id}">'
                    f"{_render_rich_text(rendered_text)}</a></li>"
                )
            elif source_type == "list":
                article_rows.append(
                    self._render_list(rendered_text)
                )
            else:
                article_rows.append(
                    f"<p>{_render_rich_text(rendered_text)}</p>"
                )
            if translation.translation_zh:
                article_rows.append(
                    '<details class="source-text" '
                    f'data-block="{_escape(block.block_id)}" '
                    f'data-page="{block.page}">'
                    f"<summary>英文原文 · p{block.page} "
                    f"{_escape(block.block_id)}</summary>"
                    f'<p lang="en">{_render_rich_text(block.text)}</p>'
                    "</details>"
                )
            else:
                article_rows[-1] = article_rows[-1].replace(
                    ">",
                    f' class="reading-block reference-block" '
                    f'data-block="{_escape(block.block_id)}" '
                    f'data-page="{block.page}">',
                    1,
                )
        article_rows.extend(
            self._render_assets(workspace, pending_assets, caption_links)
        )

        authors = "、".join(metadata.authors)
        details = [
            f"<p>作者：{_escape(authors)}</p>",
            f"<p>期刊：{_escape(metadata.journal or '未提供')}</p>",
            f"<p>年份：{_escape(metadata.year or '未提供')}</p>",
        ]
        if metadata.doi:
            details.append(f"<p>DOI：{_escape(metadata.doi)}</p>")
        return (
            "<!doctype html>\n"
            '<html lang="zh-CN"><head><meta charset="utf-8">'
            f"<title>{_escape(metadata.title)}</title><style></style>"
            "</head><body><main class=\"paper\">"
            f'<div class="paper-meta">{"".join(details)}</div>'
            f'<nav class="toc"><ul>{"".join(toc_rows)}</ul></nav>'
            f"<article>{''.join(article_rows)}</article>"
            "</main></body></html>"
        )

    @staticmethod
    def _text_levels(
        blocks: tuple[SourceBlock, ...],
    ) -> dict[str, int | None]:
        return {
            block.block_id: block.heading_level
            for block in blocks
            if block.heading_level is not None
        }

    @staticmethod
    def _render_list(value: str) -> str:
        items = [
            line.strip().removeprefix("-").strip()
            for line in value.splitlines()
            if line.strip()
        ]
        return "<ul>" + "".join(
            f"<li>{_render_rich_text(item)}</li>" for item in items
        ) + "</ul>"

    def _render_assets(
        self,
        workspace: PaperWorkspace,
        assets: Iterable[AssetRecord],
        caption_links: dict[str, Translation] | None = None,
    ) -> list[str]:
        return [
            self._render_asset(
                workspace, asset,
                caption_links.get(asset.asset_id) if caption_links else None,
            )
            for asset in assets
        ]

    @staticmethod
    def _render_asset(
        workspace: PaperWorkspace,
        asset: AssetRecord,
        caption_translation: Translation | None = None,
    ) -> str:
        active_root = (workspace.parsed_dir / "mineru").resolve()
        path = (workspace.root / asset.relative_path).resolve()
        expected_prefix = "parsed/mineru/"
        if (
            not asset.relative_path.replace("\\", "/").startswith(
                expected_prefix
            )
            or not path.is_relative_to(active_root)
            or not path.is_file()
        ):
            raise ValueError("active_asset_path_invalid")
        if caption_translation is not None:
            caption = (
                f'<div class="asset-caption">{_render_rich_text(caption_translation.translation_zh)}</div>'
                '<details class="source-text" '
                f'data-block="{_escape(caption_translation.block_id)}" data-page="{asset.page}">'
                f'<summary>英文图注 · p{asset.page} {caption_translation.block_id}</summary>'
                f'<p lang="en">{_render_rich_text(caption_translation.source_text)}</p></details>'
            )
        else:
            caption = f"<figcaption>{_render_rich_text(asset.caption)}</figcaption>" if asset.caption else ""
        if path.suffix.casefold() == ".html":
            source = BeautifulSoup(
                path.read_text(encoding="utf-8"),
                "html.parser",
            )
            safe = BeautifulSoup("", "html.parser")
            rendered_tables = []
            for source_table in source.find_all("table"):
                table = safe.new_tag("table")
                caption_tag = source_table.find("caption")
                if caption_tag is not None:
                    table_caption = safe.new_tag("caption")
                    table_caption.string = caption_tag.get_text(
                        " ",
                        strip=True,
                    )
                    table.append(table_caption)
                for source_row in source_table.find_all("tr"):
                    row = safe.new_tag("tr")
                    for source_cell in source_row.find_all(
                        ["th", "td"],
                        recursive=False,
                    ):
                        cell = safe.new_tag(source_cell.name)
                        _append_rich_text(
                            cell,
                            source_cell.get_text(" ", strip=True),
                        )
                        row.append(cell)
                    if row.contents:
                        table.append(row)
                rendered_tables.append(str(table))
            body = "".join(rendered_tables)
            if not body:
                body = f"<pre>{_escape(source.get_text(' ', strip=True))}</pre>"
        else:
            mime = mimetypes.guess_type(path.name)[0]
            if not mime or not mime.startswith("image/"):
                raise ValueError("active_asset_type_invalid")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            body = (
                f'<img src="data:{mime};base64,{encoded}" '
                f'alt="{_escape(asset.caption or asset.asset_id)}">'
            )
        caption_attribute = (
            f' data-caption-block="{_escape(caption_translation.block_id)}"'
            if caption_translation is not None else ""
        )
        return (
            f'<figure class="paper-asset {asset.kind}" '
            f'data-page="{asset.page}" '
            f'data-asset="{_escape(asset.asset_id)}"{caption_attribute}>'
            f"{body}{caption}</figure>"
        )

    @staticmethod
    def _display_assets(
        assets: tuple[AssetRecord, ...],
    ) -> tuple[AssetRecord, ...]:
        companions = {
            asset.asset_id.removesuffix("-html"): asset
            for asset in assets
            if asset.kind == "table" and asset.asset_id.endswith("-html")
        }
        displayed: list[AssetRecord] = []
        for asset in assets:
            if asset.kind != "table":
                displayed.append(asset)
                continue
            base_id = asset.asset_id.removesuffix("-html")
            preferred = companions.get(base_id)
            if preferred is not None:
                if asset.asset_id.endswith("-html"):
                    displayed.append(asset)
            else:
                displayed.append(asset)
        return tuple(displayed)

    @staticmethod
    def _asset_source_indices(
        workspace: PaperWorkspace,
        assets: tuple[AssetRecord, ...],
        blocks: tuple[SourceBlock, ...],
    ) -> dict[str, int]:
        candidates = list(
            (workspace.parsed_dir / "mineru" / "raw").rglob(
                "*_content_list.json"
            )
        )
        if len(candidates) != 1:
            page_ends = {
                page: max(
                    block.source_index or 0
                    for block in blocks if block.page == page
                )
                for page in {block.page for block in blocks}
            }
            return {
                asset.asset_id: page_ends.get(asset.page, 10**9)
                for asset in assets
            }
        items = json.loads(candidates[0].read_text(encoding="utf-8"))
        counts: dict[tuple[str, int], int] = {}
        raw_indices: dict[tuple[str, int, int], int] = {}
        for index, item in enumerate(items):
            kind = item.get("type")
            if kind not in {"image", "table"}:
                continue
            page = int(item["page_idx"]) + 1
            key = (kind, page)
            counts[key] = counts.get(key, 0) + 1
            raw_indices[(kind, page, counts[key])] = index
        result: dict[str, int] = {}
        for asset in assets:
            kind = "image" if asset.kind == "figure" else "table"
            match = re.search(r"(?:img|table)([0-9]{4})", asset.asset_id)
            if match is None:
                raise ValueError("active_asset_order_ambiguous")
            index = raw_indices.get((kind, asset.page, int(match.group(1))))
            if index is None:
                raise ValueError("active_asset_order_ambiguous")
            result[asset.asset_id] = index
        return result

    @staticmethod
    def _is_self_contained(value: str) -> bool:
        soup = BeautifulSoup(value, "html.parser")
        resource_attributes = {
            "src",
            "href",
            "srcset",
            "poster",
            "action",
            "formaction",
            "background",
        }
        for tag in soup.find_all(True):
            for name, raw_value in tag.attrs.items():
                lowered_name = name.casefold()
                if lowered_name.startswith("on"):
                    return False
                values = (
                    raw_value
                    if isinstance(raw_value, list)
                    else [raw_value]
                )
                for item in values:
                    lowered = str(item).strip().casefold()
                    if lowered_name == "style" and "url(" in lowered:
                        return False
                    if lowered_name in resource_attributes:
                        if lowered.startswith(("http:", "https:", "//")):
                            return False
                        if lowered_name == "src" and not lowered.startswith(
                            "data:"
                        ):
                            return False
            if (
                tag.name == "meta"
                and str(tag.get("http-equiv", "")).casefold() == "refresh"
            ):
                return False
        return True
