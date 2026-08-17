"""情节图模块：事件节点 + 有向边的读写（架构 §3.2）。

当前实现策略：
  - 事件节点在 events 表（由提取/生成管线写入）
  - 有向边在 event_edges 表（causal/temporal/conflict）
  - 本模块提供图的查询视角：某事件的后继/前驱、某人物参与的因果链
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Character, Event, EventEdge


def add_edge(
    db: Session,
    from_event_id: int,
    to_event_id: int,
    kind: str = "causal",
    note: str | None = None,
) -> EventEdge:
    """加一条有向边（去重）。"""
    exists = (
        db.query(EventEdge)
        .filter(
            EventEdge.from_event_id == from_event_id,
            EventEdge.to_event_id == to_event_id,
            EventEdge.kind == kind,
        )
        .first()
    )
    if exists:
        if note and not exists.note:
            exists.note = note
        return exists
    e = EventEdge(
        from_event_id=from_event_id,
        to_event_id=to_event_id,
        kind=kind,
        note=note,
    )
    db.add(e)
    db.commit()
    return e


def successors(db: Session, event_id: int) -> list[EventEdge]:
    """某事件的直接后继（因果/时序边）。"""
    return (
        db.query(EventEdge)
        .filter(EventEdge.from_event_id == event_id)
        .order_by(EventEdge.id)
        .all()
    )


def predecessors(db: Session, event_id: int) -> list[EventEdge]:
    """某事件的直接前驱。"""
    return (
        db.query(EventEdge)
        .filter(EventEdge.to_event_id == event_id)
        .order_by(EventEdge.id)
        .all()
    )


def chain_for_person(
    db: Session, character_id: int, chapter_start: int = 1, chapter_end: int | None = None
) -> list[Event]:
    """某人物参与的事件链（按回序+序号排）。

    用于"人物的故事线"视图——世界模型验收物之一。
    """
    q = db.query(Event).filter(Event.participants.contains(character_id))
    if chapter_end is not None:
        q = q.join(Event.chapter).filter(Event.chapter_id.in_(
            db.query(Event.chapter_id).filter(Event.chapter.has(num>=chapter_start, num<=chapter_end))
        ))
    return q.order_by(Event.id).all()


def person_causal_chain(db: Session, character_id: int) -> list[dict]:
    """某人物参与事件的因果链（经 event_edges 传递，简单 2 层）。"""
    evs = chain_for_person(db, character_id)
    if not evs:
        return []
    ids = {e.id: e for e in evs}
    # 找出这些事件之间的直接因果边
    edges = (
        db.query(EventEdge)
        .filter(EventEdge.from_event_id.in_(list(ids)), EventEdge.kind == "causal")
        .all()
    )
    by_from: dict[int, list[EventEdge]] = {}
    for ed in edges:
        by_from.setdefault(ed.from_event_id, []).append(ed)
    out = []
    for e in evs:
        nxt = [
            {"event_id": ed.to_event_id, "note": ed.note}
            for ed in by_from.get(e.id, [])
        ]
        out.append({"event": e, "next": nxt})
    return out


def graph_stats(db: Session) -> dict:
    """情节图统计（world 页用）。"""
    n_nodes = db.query(Event).count()
    n_edges = db.query(EventEdge).count()
    n_causal = (
        db.query(EventEdge).filter(EventEdge.kind == "causal").count()
    )
    return {
        "nodes": n_nodes,
        "edges": n_edges,
        "causal": n_causal,
        "temporal": n_edges - n_causal,
    }
