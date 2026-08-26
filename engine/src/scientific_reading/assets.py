from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .models import AssetRecord
from .workspace import atomic_write_json


@dataclass(frozen=True, slots=True)
class AssetManifest:
    path: Path

    def load(self) -> list[AssetRecord]:
        if not self.path.is_file():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [AssetRecord.from_dict(value) for value in payload.get("assets", [])]

    def load_raw(self) -> dict:
        if not self.path.is_file():
            return {"version": 1, "assets": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(
            payload.get("assets"), list
        ):
            raise ValueError("asset_manifest_invalid")
        return payload

    def upsert(self, asset: AssetRecord) -> None:
        self._validate(asset)
        assets = self.load()
        for index, existing in enumerate(assets):
            if existing.asset_id == asset.asset_id:
                assets[index] = asset
                break
        else:
            assets.append(asset)
        atomic_write_json(
            self.path,
            {
                "version": 1,
                "assets": [value.to_dict() for value in assets],
            },
        )

    @staticmethod
    def _validate(asset: AssetRecord) -> None:
        posix_path = PurePosixPath(asset.relative_path)
        windows_path = PureWindowsPath(asset.relative_path)
        if (
            not asset.relative_path.strip()
            and not asset.bbox_reliable
        ) or (
            asset.relative_path.strip()
            and (
                not posix_path.parts
                or posix_path.is_absolute()
                or windows_path.is_absolute()
                or bool(windows_path.drive)
                or bool(windows_path.root)
                or ".." in posix_path.parts
                or ".." in windows_path.parts
            )
        ):
            raise ValueError("relative_path 必须位于论文工作目录内")
        if not asset.asset_id.strip():
            raise ValueError("asset_id 不能为空")
        if asset.kind not in {"figure", "table"}:
            raise ValueError("kind 必须是 figure 或 table")
        if asset.page < 1:
            raise ValueError("page 必须大于零")
        if asset.source_index is not None and (
            isinstance(asset.source_index, bool)
            or not isinstance(asset.source_index, int)
            or asset.source_index < 0
        ):
            raise ValueError("source_index 无效")
        if asset.is_body is not None and not isinstance(
            asset.is_body, bool
        ):
            raise ValueError("is_body 无效")
        if asset.bbox is not None and (
            len(asset.bbox) != 4
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in asset.bbox
            )
        ):
            raise ValueError("bbox 无效")
        if asset.bbox_reliable and asset.bbox is None:
            raise ValueError("bbox_reliable 缺少 bbox")
        for value, name in (
            (asset.source_sha256, "source_sha256"),
            (asset.structured_sha256, "structured_sha256"),
        ):
            if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} 无效")
        if asset.structured_reliable:
            if not asset.structured_path or not asset.structured_sha256:
                raise ValueError("可靠结构化表来源不完整")
            structured_posix = PurePosixPath(asset.structured_path)
            structured_windows = PureWindowsPath(asset.structured_path)
            if (
                structured_posix.is_absolute()
                or structured_windows.is_absolute()
                or structured_windows.drive
                or structured_windows.root
                or ".." in structured_posix.parts
                or ".." in structured_windows.parts
            ):
                raise ValueError("structured_path 必须位于论文工作目录内")
