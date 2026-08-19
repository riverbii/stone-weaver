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

BEAT_PROMPT = """你是红楼梦叙事分析专家。下面是《癸酉本》第{chapter}回原文。请把本回情节拆解为**细粒度情节点序列**（4-8 个），每个情节点对应一个独立的场景单元。

只输出一个 JSON 对象，不要其他文字：
{{"scene": "本回总体场景", "goal": "本回核心目标（一句话）", "characters": ["核心人物"], "constraints": ["关键约束"], "expected_out": "本回结束时世界状态变化", "points": [{{"scene": "情节点场景地点", "goal": "该情节点发生的事（一句话，含人物动作与结果）", "characters": ["该情节点人物"], "expected_out": "该情节点结束后的状态"}}]}}

规则：
- **points 要细**：把本回拆成 4-8 个连续场景单元，每个都具体到"谁在哪儿做了什么、结果如何"
  （如"王夫人裁月钱→宝玉求情→婆子结党"应拆成 2-3 个 points）
- goal 只写"发生了什么"，不写"怎么写的"（文风由生成器负责）
- points 的 expected_out 要具体可校验

原文：
{text}
"""


@dataclass
class PlotPoint:
    """细粒度情节点：一个场景单元（比 Beat 小一级）。

    一回拆成多个 PlotPoint（4-8 个），生成器逐个生成后拼装成完整回目。
    """

    scene: str
    goal: str
    characters: list[str] = field(default_factory=list)
    expected_out: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "goal": self.goal,
            "characters": self.characters,
            "expected_out": self.expected_out,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlotPoint":
        return cls(
            scene=d.get("scene", ""),
            goal=d.get("goal", ""),
            characters=d.get("characters") or [],
            expected_out=d.get("expected_out", ""),
        )


@dataclass
class Beat:
    """单回叙事节拍：本回核心目标 + 细粒度情节点序列。"""

    scene: str
    goal: str
    characters: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_out: str = ""
    points: list[PlotPoint] = field(default_factory=list)  # 细粒度情节点

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "goal": self.goal,
            "characters": self.characters,
            "constraints": self.constraints,
            "expected_out": self.expected_out,
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Beat":
        return cls(
            scene=d.get("scene", ""),
            goal=d.get("goal", ""),
            characters=d.get("characters") or [],
            constraints=d.get("constraints") or [],
            expected_out=d.get("expected_out", ""),
            points=[PlotPoint.from_dict(p) for p in (d.get("points") or [])],
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


def _extract_beat_chunk(client: LLMClient, text: str, chapter: int, chunk_tag: str = "") -> Beat | None:
    """对一段文本提取 beat（含 points）。"""
    prompt = (
        BEAT_PROMPT.replace("{{", "{")
        .replace("}}", "}")
        .replace("{text}", text)
        .replace("{chapter}", f"{chapter}{chunk_tag}")
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


def extract_beat(client: LLMClient, chapter: Chapter, chunk_size: int = 5000) -> Beat | None:
    """单回压缩为 beat（容错：JSON 围栏/杂文；HTTP 异常上抛由调用方重试）。

    全文分段提取再合并：单回可达 1.3 万字（癸酉本），只取前 6000 字会丢失
    后半段情节（如 81 回香菱段在 9235 位置）。每段提取 points 后拼接。
    """
    text = chapter.content
    if len(text) <= chunk_size:
        return _extract_beat_chunk(client, text, chapter.num)

    # 分段：按段落边界切，每段约 chunk_size
    chunks = []
    cur = []
    cur_len = 0
    for p in text.split("\n"):
        if cur and cur_len + len(p) > chunk_size:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p)
    if cur:
        chunks.append("\n".join(cur))

    beats = []
    for i, c in enumerate(chunks, 1):
        b = _extract_beat_chunk(client, c, chapter.num, f"（片段{i}/{len(chunks)}）")
        if b:
            beats.append(b)

    if not beats:
        return None
    if len(beats) == 1:
        return beats[0]

    # 合并：goal 取第一段，points 全部拼接（去重同场景）
    merged = beats[0]
    seen_goals = {p.goal for p in merged.points}
    for b in beats[1:]:
        for p in b.points:
            if p.goal not in seen_goals:
                merged.points.append(p)
                seen_goals.add(p.goal)
    # 补充 characters/constraints
    for b in beats[1:]:
        for c in b.characters:
            if c not in merged.characters:
                merged.characters.append(c)
        for c in b.constraints:
            if c not in merged.constraints:
                merged.constraints.append(c)
    return merged


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
