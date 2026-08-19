#!/usr/bin/env python3
"""前80回末（ch80）人物状态核查：用 LLM 判定关键人物生死/位置/状态。

背景：规则版死亡标记（initial_state_from_events）太粗糙——关键词误伤
（"X讲别人死"把X标死）或漏标（summary措辞不含关键词）。本脚本用一次
LLM 调用，基于前80回事件摘要，输出关键人物的世界状态快照 → 写入
character_states 表（ch80），作为 80→81 衔接的输入。

用法:
  .venv/bin/python scripts/build_ch80_state.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import Character, CharacterState, Chapter, Event
from stone_weaver.world.state import state_at

PROMPT = """你是红楼梦世界状态考据专家。下面是《红楼梦》前80回按回排列的事件摘要。

请判定**关键人物**在"第80回末"的世界状态，只输出 JSON 对象：
{{"characters": [{{"name": "人物标准姓名", "alive": true/false, "location": "当前所在地点，未知留空", "status": "特殊状态如 出家/病重/发配/无", "note": "一句话依据（引用事件）"}}]}}

要求：
- 只列有明确状态依据的人物（死了/出家/远嫁/病重/被逐等），不确定的不要列
- alive=false 必须基于明确死亡事件（秦可卿/贾瑞/金钏/尤二姐/尤三姐/晴雯/黛玉之母等）
- 人物用标准姓名

事件摘要（按回）：
{events}
"""


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()

    # 聚合前80回事件摘要（每回取前 6 条，控制 token）
    lines = []
    for ch in (
        db.query(Chapter)
        .filter(Chapter.version == "gongban_rb", Chapter.num <= 80)
        .order_by(Chapter.num)
        .all()
    ):
        evs = (
            db.query(Event)
            .filter(Event.chapter_id == ch.id)
            .order_by(Event.seq)
            .limit(6)
            .all()
        )
        for e in evs:
            lines.append(f"第{ch.num}回: {e.summary[:80]}")
    events_text = "\n".join(lines)
    print(f"事件摘要 {len(lines)} 条，{len(events_text)} 字符", flush=True)

    prompt = PROMPT.replace("{events}", events_text[:15000])
    raw = client.chat([{"role": "system", "content": prompt}], temperature=0.1)
    a, b = raw.find("{"), raw.rfind("}")
    if a == -1 or b <= a:
        print("❌ JSON 解析失败")
        return 1
    data = json.loads(raw[a : b + 1])
    chars = data.get("characters") or []
    print(f"判定 {len(chars)} 个人物状态:", flush=True)

    # 清空旧 ch80 快照，写入新状态
    db.query(CharacterState).filter(CharacterState.chapter == 80).delete()
    n_written = 0
    for item in chars:
        name = (item.get("name") or "").strip()
        c = db.query(Character).filter(Character.name == name).first()
        if c is None:
            # 按别名匹配（LLM 可能输出别名如 香菱/迎春）
            for cc in db.query(Character).filter(Character.kind == "story").all():
                if name in (cc.aliases or []):
                    c = cc
                    break
        if c is None:
            print(f"  ⚠️ 未知人物 {name}，跳过", flush=True)
            continue
        # 幂等：先删该人物 ch80 已有快照（可能别名重复匹配）
        db.query(CharacterState).filter(
            CharacterState.character_id == c.id,
            CharacterState.chapter == 80,
        ).delete()
        db.add(
            CharacterState(
                character_id=c.id,
                chapter=80,
                alive=bool(item.get("alive", True)),
                location=item.get("location") or None,
                status=item.get("status") or None,
                note=item.get("note") or None,
            )
        )
        n_written += 1
        mark = "已故" if not item.get("alive", True) else "在世"
        print(f"  {name}: {mark} {item.get('status') or ''} {item.get('location') or ''}", flush=True)
    db.commit()
    print(f"\n✅ 写入 {n_written} 条 ch80 状态快照")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
