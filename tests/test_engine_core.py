"""叙事引擎校验器 + 情节弧 + 文风评估 单元测试（不依赖 LLM）。"""

from __future__ import annotations

import pytest

from stone_weaver.engine.arc import Arc, Beat
from stone_weaver.engine.validate import Violation, feedback_prompt, validate_rules
from stone_weaver.style.assess import assess, verdict
from stone_weaver.world.state import PersonStatus, WorldState


def make_state(**persons) -> WorldState:
    ws = WorldState(chapter=80)
    for name, alive in persons.items():
        ws.persons[hash(name) % 100000] = PersonStatus(
            character_id=hash(name) % 100000, name=name, alive=alive
        )
    return ws


def test_validate_rules_dead_person_blocked():
    state = make_state(林黛玉=False, 贾宝玉=True)
    evs = [
        {"summary": "黛玉与宝玉谈心", "participants": ["林黛玉", "贾宝玉"]},
        {"summary": "宝玉独坐", "participants": ["贾宝玉"]},
    ]
    v = validate_rules(state, evs)
    assert len(v) == 1
    assert v[0].rule == "dead_present"
    assert "林黛玉" in v[0].message


def test_validate_rules_clean_passes():
    state = make_state(林黛玉=True, 贾宝玉=True)
    evs = [{"summary": "二人谈心", "participants": ["林黛玉", "贾宝玉"]}]
    assert validate_rules(state, evs) == []


def test_feedback_prompt():
    vs = [Violation(rule="dead_present", message="黛玉已故却出场")]
    fb = feedback_prompt(vs)
    assert "一致性校验反馈" in fb
    assert "黛玉已故却出场" in fb
    assert feedback_prompt([]) == ""


def test_arc_roundtrip():
    arc = Arc(
        name="测试弧",
        version="test",
        beats=[Beat(scene="柳叶渚", goal="黛玉自缢", characters=["黛玉"], expected_out="黛玉死")],
    )
    d = arc.to_dict()
    assert d["beats"][0]["goal"] == "黛玉自缢"
    b2 = Beat.from_dict(d["beats"][0])
    assert b2.scene == "柳叶渚"
    assert b2.expected_out == "黛玉死"


def test_style_assess_distinguishes():
    classical = "话说这日宝玉来至沁芳桥畔，只见落花满地，因叹道：女儿是水做的骨肉，我见了女儿便清爽。"
    modern = "然后他突然觉得非常难过，因为他的朋友已经离开了，所以他一个人坐在那里，其实他真的很想哭。"
    a1 = assess(classical)
    a2 = assess(modern)
    assert a1["score"] > a2["score"]
    assert verdict(a1) in ("✅ 文风达标", "🟡 文风接近，需润色")
    assert verdict(a2) == "❌ 文风不符，需重写"
