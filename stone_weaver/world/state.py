"""世界状态模块：人物动态状态的查询、快照、事件应用。

架构定位（docs/architecture.md §3.3）：
  世界状态 = 人物动态状态 + 情节图当前节点 + 未决线索。
  本模块负责前两部分的数据层操作，纯函数可测。

核心原则：
  - 人物状态按"回"做版本（character_states 表，只写变化回）
  - 查询取 chapter<=N 的最新一条 = 该回时点的状态
  - 状态更新唯一路径：apply_event（事件驱动，避免状态与文本漂移）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Character, CharacterState


@dataclass
class PersonStatus:
    """某人物在某回时点的动态状态（从 character_states 最新快照还原）。"""

    character_id: int
    name: str
    chapter: int = 1
    alive: bool = True
    location: str | None = None
    status: str | None = None

    def summary(self) -> str:
        parts = [self.name]
        if not self.alive:
            parts.append("已故")
        if self.status:
            parts.append(self.status)
        if self.location:
            parts.append(f"在{self.location}")
        return "，".join(parts)


@dataclass
class WorldState:
    """聚合世界状态：人物状态索引 + 当前回。"""

    chapter: int = 0
    persons: dict[int, PersonStatus] = field(default_factory=dict)

    def person(self, cid: int) -> PersonStatus | None:
        return self.persons.get(cid)

    def alive_ids(self) -> list[int]:
        return [cid for cid, p in self.persons.items() if p.alive]

    def describe(self, limit: int = 30) -> str:
        """给 LLM 生成器的状态简报：谁活着、谁在哪、特殊状态。"""
        alive = sorted(
            (p for p in self.persons.values() if p.alive),
            key=lambda p: p.name,
        )
        notable = [
            p for p in self.persons.values()
            if not p.alive or p.status or p.location
        ]
        lines = [f"当前在第{self.chapter}回之后。"]
        if notable:
            lines.append("关键状态：" + "；".join(p.summary() for p in notable[:limit]))
        if alive:
            names = "、".join(p.name for p in alive[:40])
            lines.append(f"在世人物（前40）：{names}")
        return "\n".join(lines)


def state_at(db: Session, chapter: int, story_only: bool = True) -> WorldState:
    """重建 chapter 回时点的世界状态。

    story_only=True 时只含 story 人物（排除典故引用，降低噪声）。
    """
    ws = WorldState(chapter=chapter)
    chars = db.query(Character).order_by(Character.id)
    if story_only:
        chars = chars.filter(Character.kind == "story")
    chars = chars.all()

    # 每条人物最新快照（chapter<=N 的一条）
    for c in chars:
        snap = (
            db.query(CharacterState)
            .filter(
                CharacterState.character_id == c.id,
                CharacterState.chapter <= chapter,
            )
            .order_by(CharacterState.chapter.desc())
            .first()
        )
        if snap is not None:
            ws.persons[c.id] = PersonStatus(
                character_id=c.id,
                name=c.name,
                chapter=snap.chapter,
                alive=snap.alive,
                location=snap.location,
                status=snap.status,
            )
        else:
            # 无快照 = 尚未记录状态变化（默认在世，位置未知）
            ws.persons[c.id] = PersonStatus(character_id=c.id, name=c.name)
    return ws


def apply_event(
    db: Session,
    state: WorldState,
    *,
    character_id: int,
    chapter: int,
    alive: bool | None = None,
    location: str | None = None,
    status: str | None = None,
    note: str | None = None,
) -> CharacterState:
    """应用一个状态变更事件，写入快照并更新内存状态。返回新快照。

    只写有变化的回；同一 (character_id, chapter) 重复写时覆盖。
    """
    cur = state.persons.get(character_id)
    base = PersonStatus(
        character_id=character_id,
        name=cur.name if cur else str(character_id),
        chapter=state.chapter,
        alive=cur.alive if cur else True,
        location=cur.location if cur else None,
        status=cur.status if cur else None,
    )
    new_alive = base.alive if alive is None else alive
    new_loc = base.location if location is None else location
    new_status = base.status if status is None else status

    if (
        new_alive == base.alive
        and new_loc == base.location
        and new_status == base.status
    ):
        # 无实质变化，不写库
        return None  # type: ignore[return-value]

    snap = (
        db.query(CharacterState)
        .filter(
            CharacterState.character_id == character_id,
            CharacterState.chapter == chapter,
        )
        .one_or_none()
    )
    if snap is None:
        snap = CharacterState(character_id=character_id, chapter=chapter)
        db.add(snap)
    snap.alive = new_alive
    snap.location = new_loc
    snap.status = new_status
    snap.note = note
    db.commit()

    state.persons[character_id] = PersonStatus(
        character_id=character_id,
        name=base.name,
        chapter=chapter,
        alive=new_alive,
        location=new_loc,
        status=new_status,
    )
    state.chapter = max(state.chapter, chapter)
    return snap


def initial_state_from_events(db: Session, chapter: int = 80) -> WorldState:
    """从事件表推导前 N 回末的世界状态（80→81 衔接用）。

    规则版（无 LLM）：扫描前 N 回事件的 summary，用死亡/状态关键词
    标记已故人物（如"黛玉自缢""元春被赐死"）。位置等细粒度状态
    等事件表有结构化数据后扩展。
    """
    ws = state_at(db, chapter)
    from ..models import Chapter, Character, Event

    # 死亡关键词 → 仅当事件参与者唯一 且 summary 含死亡语义时标记
    # （避免"X讲别人死了"把 X 误标；粗糙规则，阶段3 用 LLM 精修）
    death_hints = ("自缢", "病逝", "身亡", "被杀", "刺死", "赐死", "薨逝", "亡故", "死了", "死去", "殁")
    story_ids = {
        c.id: c for c in db.query(Character).filter(Character.kind == "story")
    }
    evs = (
        db.query(Event)
        .join(Event.chapter)
        .filter(Chapter.num <= chapter)
        .all()
    )
    for ev in evs:
        if not any(h in ev.summary for h in death_hints):
            continue
        pids = [p for p in (ev.participants or []) if p in story_ids]
        # 参与者唯一且 summary 是"该人死了"类 → 标记
        if len(pids) == 1 and any(h in ev.summary for h in ("自缢", "病逝", "身亡", "被杀", "刺死", "赐死", "薨逝", "亡故")):
            pid = pids[0]
            ws.persons[pid].alive = False
            ws.persons[pid].status = "已故"
            ws.persons[pid].note = ev.summary[:80]
    return ws
