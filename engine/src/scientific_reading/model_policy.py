"""逐步骤模型偏好；与文献库一起保存，模型能力由宿主实时验证。"""
from __future__ import annotations

import json

from .data_guard import root_operation
from .scope import require_global


STEPS = (
    ("radar_direction", "雷达：研究方向", "gpt-5.6-sol"),
    ("radar_assessment", "雷达：候选评估", "gpt-5.6-sol"),
    ("abstract_translation", "摘要翻译", "gpt-5.6-luna"),
    ("full_translation", "全文与图注翻译", "gpt-5.6-luna"),
    ("full_review", "全文导读与重点高亮", "gpt-5.6-sol"),
    ("classification", "分类建议", "gpt-5.6-sol"),
    ("research_fields", "研究字段提取", "gpt-5.6-sol"),
    ("paper_chat", "单篇讨论", "gpt-5.6-sol"),
    ("figure_chat", "Figure 讨论", "gpt-5.6-sol"),
    ("multi_paper_summary", "多篇综合", "gpt-5.6-sol"),
    ("reader_chat", "阅读悬浮对话与选区解释", "gpt-5.6-sol"),
)
KEY = "models.steps.v1"


def read(library):
    row = library.conn.execute("SELECT value FROM library_meta WHERE key=?", (KEY,)).fetchone()
    saved = json.loads(row[0]) if row else {"revision": 0, "steps": {}}
    return {"revision": saved["revision"], "steps": {
        step: {"label": label, "provider": "", "model": model, "reasoningEffort": "medium",
               **saved["steps"].get(step, {})} for step, label, model in STEPS}}


@root_operation
def save(library, payload):
    require_global("model_policy_save")
    updates = payload.get("steps")
    if not isinstance(updates, dict) or not updates or set(updates) - {row[0] for row in STEPS}:
        raise ValueError("model_step_invalid")
    for value in updates.values():
        if not isinstance(value, dict) or set(value) != {"provider", "model", "reasoningEffort"}:
            raise ValueError("model_policy_invalid")
        if any(not isinstance(text, str) or len(text) > 240 or any(ord(c) < 32 for c in text)
               for text in value.values()) or not value["model"].strip():
            raise ValueError("model_policy_invalid")
    with library.conn:
        library.conn.execute("BEGIN IMMEDIATE")
        current = read(library)
        if type(payload.get("revision")) is not int or payload["revision"] != current["revision"]:
            raise ValueError("model_policy_changed")
        steps = {key: {field: value[field] for field in ("provider", "model", "reasoningEffort")}
                 for key, value in current["steps"].items()}
        steps.update(updates)
        library.conn.execute("INSERT INTO library_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (KEY, json.dumps({"revision": current["revision"] + 1, "steps": steps})))
    return read(library)
