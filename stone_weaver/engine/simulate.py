"""叙事引擎 · 主循环。

架构定位（docs/architecture.md §5）：
  simulate_one_beat 是阶段2 的最小闭环（先单 beat 验证质量，再扩展整回）。

流程：
  plan → generate → extract → validate_rules → 落库(events/event_edges/character_states)
  规则校验失败 → 带反馈重生成（最多 max_retries 次）
"""

from __future__ import annotations

import json
import time

from sqlalchemy.orm import Session

from ..llm import LLMClient
from ..models import Character, Event, EventEdge, GeneratedChapter
from ..style.anchors import StyleAnchor
from ..world.state import WorldState, apply_event
from .generate import generate_and_extract
from .validate import Violation, feedback_prompt, validate_personality, validate_rules


def _name_to_id(db: Session, name: str) -> int | None:
    c = db.query(Character).filter(Character.name == name).first()
    if c:
        return c.id
    c = db.query(Character).filter(Character.kind == "story").all()
    for cc in c:
        if name in (cc.aliases or []):
            return cc.id
    return None


def simulate_one_beat(
    db: Session,
    client: LLMClient,
    beat: dict,
    state: WorldState,
    anchors: list[StyleAnchor],
    *,
    chapter_num: int,
    title: str = "",
    max_retries: int = 3,
    persist: bool = True,
    cliche_gate: bool = False,
) -> dict:
    """执行一个 beat 的完整循环。返回结果 dict（供调用方检查）。

    cliche_gate=True 时套路词超量触发重生成（慢，仅质量攻坚用）；
    False（默认）时只记录套路词问题不阻断（批量生成用）。
    """
    result: dict = {
        "ok": False,
        "text": "",
        "events": [],
        "violations": [],
        "retries": 0,
    }
    active_beat = dict(beat)
    for attempt in range(max_retries):
        try:
            text, evs = generate_and_extract(client, active_beat, state, anchors)
        except Exception as e:  # noqa: BLE001
            result["retries"] = attempt + 1
            print(f"    生成异常（{type(e).__name__}），重试 {attempt+1}/{max_retries}", flush=True)
            continue
        if not text:
            result["retries"] = attempt + 1
            continue
        v_rule = validate_rules(state, evs)
        if v_rule:
            # 带反馈重生成
            fb = feedback_prompt(v_rule)
            active_beat = dict(active_beat)
            active_beat["_feedback"] = fb
            result["violations"] = v_rule
            result["retries"] = attempt + 1
            continue
        # 套路词检查（生成后把关：半晌/怔了/眼圈等 LLM 套路词）
        from ..style.cliches import check_style

        cliche_problems = check_style(text)
        if cliche_problems and cliche_gate:
            active_beat = dict(active_beat)
            active_beat["_feedback"] = (
                "【文风套路检查反馈——请重写并消除以下套路】\n" + "\n".join(f"- {p}" for p in cliche_problems)
            )
            result["violations"] = cliche_problems
            result["retries"] = attempt + 1
            print(f"    套路词超量（{'；'.join(p[:22] for p in cliche_problems)}），重试 {attempt+1}/{max_retries}", flush=True)
            continue
        result["cliches"] = cliche_problems  # 记录（无论是否 gate）
        # 生成"题曰"开篇诗（结合本章情节），前置到正文
        from .generate import generate_tiyu

        tiyu = generate_tiyu(client, beat, title)
        if tiyu:
            # 诗可能已含"题曰："前缀，避免重复
            if tiyu.strip().startswith("题曰"):
                text = f"{tiyu}\n\n{text}"
            else:
                text = f"题曰：\n{tiyu}\n\n{text}"
        result["tiyu"] = tiyu
        # 规则通过 → 落库
        result["ok"] = True
        result["text"] = text
        result["events"] = evs
        result["retries"] = attempt

        if persist:
            _persist(db, evs, state, chapter_num, text, title, beat)
        # LLM 性格校验（warn 级，不影响落库，返回供参考）
        v_person = validate_personality(client, text, state)
        result["violations"] = v_rule + v_person
        return result
    return result


def _persist(
    db: Session,
    evs: list[dict],
    state: WorldState,
    chapter_num: int,
    text: str,
    title: str,
    beat: dict,
) -> None:
    """事件 + 因果边 + 状态变更 + 生成回目 落库。"""
    from ..models import Chapter

    ch = (
        db.query(Chapter)
        .filter(Chapter.version == "gongban_rb", Chapter.num == chapter_num)
        .first()
    )
    if ch is None:
        # 引擎生成回无公版对应（后28回），挂到 guihui_v3 同回下
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == "guihui_v3", Chapter.num == chapter_num)
            .first()
        )
    event_rows = []
    for i, ev in enumerate(evs, 1):
        pids = [
            _name_to_id(db, n)
            for n in (ev.get("participants") or [])
            if _name_to_id(db, n) is not None
        ]
        e = Event(
            chapter_id=ch.id if ch else None,
            seq=i,
            summary=ev.get("summary", ""),
            participants=pids,
            location=ev.get("location"),
        )
        db.add(e)
        db.flush()
        event_rows.append((e, ev))
    # 因果/时序边：cause_of 指向本数组序号 → 因果边；否则默认前驱时序边
    for e, ev in event_rows:
        idx = event_rows.index((e, ev))
        cause = ev.get("cause_of") or 0
        if isinstance(cause, int) and 1 <= cause <= len(event_rows) and cause != idx + 1:
            db.add(
                EventEdge(
                    from_event_id=event_rows[cause - 1][0].id,
                    to_event_id=e.id,
                    kind="causal",
                    note=ev.get("summary", "")[:80],
                )
            )
        elif idx > 0:
            db.add(
                EventEdge(
                    from_event_id=event_rows[idx - 1][0].id,
                    to_event_id=e.id,
                    kind="temporal",
                )
            )
    db.add(
        GeneratedChapter(
            arc_id=None,
            num=chapter_num,
            title=title or f"第{chapter_num}回",
            content=text,
            status="draft",
        )
    )
    db.commit()
    state.chapter = chapter_num
