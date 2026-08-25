"""文风审查智能体：专职评审引擎产出的文风/格律/意境/内容贴合度。

多智能体架构定位（docs/architecture.md §5 校验层升级）：
  - 生成智能体（simulate_one_beat）产出文本
  - **审查智能体（本模块）** 专职评审，输出结构化报告 + 修正建议
  - 有 error 级问题时生成智能体带反馈重写

统一了原有的分散检查：
  - 文风（原 judge.py judge_style）
  - 平仄格律（原 generate.py check_poem_geilv）
  - 套路词（原 cliches.py check_style）
  - 内容贴合（原 validate.py validate_personality 的情节维度）

用法：
  reviewer = StyleReviewer(client, db)
  report = reviewer.review(text, beat=beat, title="第82回")
  if report.has_errors(): text2 = reviewer.rewrite_with_feedback(text, report)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMClient
from .anchors import extract_anchors

REVIEW_PROMPT = """你是红楼梦续书的**文风审查官**，负责为续写文本把关。你精通曹雪芹笔法、近体诗格律，眼光犀利。

【曹雪芹风格参照】
{anchors}

【本章情节要点】（判断内容是否贴合）
{points}

【待审文本】
{target}

请从四个维度严格审查，输出 JSON：
{{"dims": [
  {{"dim": "文风", "score": 0-10, "ok": true/false, "issues": ["具体问题"], "suggest": "修正建议"}},
  {{"dim": "格律", "score": 0-10, "ok": true/false, "issues": ["平仄/押韵/对仗问题，具体到句"], "suggest": "修正建议"}},
  {{"dim": "意境", "score": 0-10, "ok": true/false, "issues": ["有无打油诗感/直白浅露/堆砌生僻字"], "suggest": "修正建议"}},
  {{"dim": "内容贴合", "score": 0-10, "ok": true/false, "issues": ["是否结合本章情节要点"], "suggest": "修正建议"}}
], "verdict": "通过/需修正", "summary": "一句话总评"}}

审查标准：
- 文风：白描/对话/文言调度是否像曹雪芹；有无现代白话痕迹、套路词（半晌/怔了/眼圈）
- 格律：题曰诗平仄相间、押平声韵、对仗（绝句对仗不强制）；正文无格律要求
- 意境：含蓄用典、有古意，非打油诗、非堆砌冷僻字
- 内容贴合：题曰/正文是否呼应本章情节（喜事/丧事/抄家/离别等）
只输出 JSON。
"""


@dataclass
class DimensionReport:
    dim: str
    score: float
    ok: bool
    issues: list[str] = field(default_factory=list)
    suggest: str = ""


@dataclass
class ReviewReport:
    dims: list[DimensionReport] = field(default_factory=list)
    verdict: str = ""
    summary: str = ""

    def has_errors(self) -> bool:
        return any(not d.ok for d in self.dims)

    def issues_text(self) -> str:
        """把问题转成反馈文本（给生成智能体重写用）。"""
        lines = []
        for d in self.dims:
            if not d.ok:
                lines.append(f"【{d.dim}】{'；'.join(d.issues)}")
                if d.suggest:
                    lines.append(f"  建议：{d.suggest}")
        return "\n".join(lines)


class StyleReviewer:
    """文风审查智能体。"""

    def __init__(self, client: LLMClient, db=None) -> None:
        self.client = client
        self.db = db

    def _anchors(self) -> str:
        if self.db is None:
            return ""
        anchors = extract_anchors(self.db, chapters=list(range(1, 41)), per_kind=1)
        return "\n".join(a.text[:200] for a in anchors[:4])

    def review(
        self,
        text: str,
        *,
        beat: dict | None = None,
        title: str = "",
    ) -> ReviewReport:
        """审查文本，返回结构化报告。"""
        points = beat.get("points") or [] if beat else []
        point_lines = "\n".join(
            f"- {p.get('scene', '')}: {p.get('goal', '')[:40]}" for p in points[:5]
        ) or (beat.get("goal", "") if beat else "")
        prompt = (
            REVIEW_PROMPT.replace("{anchors}", self._anchors())
            .replace("{points}", point_lines[:600] or "（无情节要点，仅审文风格律）")
            .replace("{target}", text[:3000])
        )
        raw = self.client.chat(
            [{"role": "system", "content": prompt}], temperature=0.2
        )
        data = self._parse(raw)
        if data is None:
            return ReviewReport(verdict="审查失败", summary="LLM 未返回有效 JSON")
        dims = []
        for d in data.get("dims") or []:
            dims.append(
                DimensionReport(
                    dim=d.get("dim", "?"),
                    score=d.get("score", 0),
                    ok=d.get("ok", False),
                    issues=d.get("issues") or [],
                    suggest=d.get("suggest", ""),
                )
            )
        return ReviewReport(
            dims=dims,
            verdict=data.get("verdict", ""),
            summary=data.get("summary", ""),
        )

    def rewrite_with_feedback(self, text: str, report: ReviewReport) -> str:
        """带审查反馈重写。"""
        fb = report.issues_text()
        prompt = (
            "你是红楼梦续写专家。请根据文风审查官的反馈，重写下面这段文本（保留情节，修正文风/格律/意境问题）。\n\n"
            f"【审查反馈】\n{fb}\n\n"
            f"【原文】\n{text[:3000]}\n\n"
            "【重写】\n"
        )
        try:
            raw = self.client.chat(
                [{"role": "system", "content": prompt}], temperature=0.6
            )
            return raw.strip() or text
        except Exception:
            return text

    @staticmethod
    def _parse(raw: str) -> dict | None:
        s = raw.strip()
        a, b = s.find("{"), s.rfind("}")
        if a == -1 or b <= a:
            return None
        try:
            data = json.loads(s[a : b + 1])
        except Exception:
            return None
        return data if isinstance(data, dict) else None
