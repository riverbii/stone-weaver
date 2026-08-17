"""情节弧模块：叙事引擎的"剧本"。

架构定位（docs/architecture.md §4）：
  Arc = 高层目标序列（beats），每个 beat 是一个场景目标。
  来源：从 guihui_v3（癸酉本108回全文，已入库）用 LLM 逐回压缩为 beat，
  产出固化为 arcs 表 + docs/guihui_arc.md 可读版。

本模块提供：
  - Arc/Beat 数据模型（内存表示）
  - build_arc_from_chapters：LLM 逐回压缩为 beat 序列（scripts/build_arc.py 调用）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..llm import LLMClient
from ..models import Arc as ArcRow
from ..models import Chapter

BEAT_PROMPT = """你是红楼梦叙事分析专家。下面是《癸酉本》第{chapter}回原文。请把本回情节压缩为一个"叙事节拍"（beat）。

只输出一个 JSON 对象，不要其他文字：
{{"scene": "场景地点", "goal": "本回核心目标（一句话，含人物动作与结果）", "characters": ["核心人物标准姓名"], "constraints": ["关键约束或前提（如时间/背景/必须承接的前事）"], "expected_out": "本回结束时的世界状态变化（谁死了/谁去了哪/关系如何变）"}}

规则：
- goal 只写"发生了什么"，不写"怎么写的"（文风由生成器负责）
- characters 只放有实际戏份的人物
- expected_out 要具体到可校验（如"林黛玉自缢于柳叶渚槐树"）

原文：
{text}
"""


@dataclass
class Beat:
    """单节拍：一个场景目标。"""

    scene: str
    goal: str
    characters: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_out: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "goal": self.goal,
            "characters": self.characters,
            "constraints": self.constraints,
            "expected_out": self.expected_out,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Beat":
        return cls(
            scene=d.get("scene", ""),
            goal=d.get("goal", ""),
            characters=d.get("characters") or [],
            constraints=d.get("constraints") or [],
            expected_out=d.get("expected_out", ""),
        )


@dataclass
class Arc:
    """情节弧：有序 beat 序列。"""

    name: str
    version: str
    beats: list[Beat] = field(default_factory=list)
    source_chapter_range: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "beats": [b.to_dict() for b in self.beats],
            "source_chapter_range": self.source_chapter_range,
        }


def extract_beat(client: LLMClient, chapter: Chapter) -> Beat | None:
    """单回压缩为 beat（容错：JSON 围栏/杂文；HTTP 异常上抛由调用方重试）。"""
    text = chapter.content[:6000]
    prompt = BEAT_PROMPT.replace("{text}", text).replace(
        "{chapter}", str(chapter.num)
    )
    raw = client.chat([{"role": "system", "content": prompt}], temperature=0.1)  # 异常上抛
    import json

    s = raw.strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        data = json.loads(s[a : b + 1])
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("goal"):
        return None
    return Beat.from_dict(data)


def build_arc_from_chapters(
    db: Session, client: LLMClient, nums: list[int], *, version: str = "guihui_v3"
) -> Arc:
    """逐回压缩为 beat 序列（断点续传：跳过已有）。"""
    beats: list[Beat] = []
    for num in nums:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == version, Chapter.num == num)
            .first()
        )
        if ch is None:
            print(f"  [{num}] ⚠️ 回目不存在，跳过", flush=True)
            continue
        beat = extract_beat(client, ch)
        if beat is None:
            print(f"  [{num}] ❌ 提取失败", flush=True)
            continue
        beat_dict = beat.to_dict()
        beat_dict["_chapter"] = num  # 记录来源回（不入库，仅过程用）
        beats.append(beat)
        print(f"  [{num}] ✅ {beat.goal[:40]}…", flush=True)
    arc = Arc(
        name=f"癸酉本后28回情节弧",
        version=version,
        beats=beats,
        source_chapter_range=f"{min(nums)}-{max(nums)}",
    )
    return arc


def save_arc(db: Session, arc: Arc) -> int:
    """落库 arcs 表（幂等：同名+版本覆盖）。返回 arc id。"""
    row = (
        db.query(ArcRow)
        .filter(ArcRow.name == arc.name, ArcRow.version == arc.version)
        .first()
    )
    if row is None:
        row = ArcRow(name=arc.name, version=arc.version)
        db.add(row)
    row.beats = [b.to_dict() for b in arc.beats]
    row.source_chapter_range = arc.source_chapter_range
    db.commit()
    return row.id


def load_arc(db: Session, arc_id: int) -> Arc:
    row = db.query(ArcRow).filter(ArcRow.id == arc_id).one()
    return Arc(
        name=row.name,
        version=row.version,
        beats=[Beat.from_dict(b) for b in (row.beats or [])],
        source_chapter_range=row.source_chapter_range,
    )
