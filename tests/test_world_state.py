"""世界状态模块单元测试（不依赖 LLM）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stone_weaver.ingest.text import make_engine, make_session
from stone_weaver.models import Base, Character, CharacterState
from stone_weaver.world.state import apply_event, state_at


@pytest.fixture()
def db(tmp_path):
    """临时 sqlite 库，塞两个测试人物。"""
    engine = make_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    s = make_session(str(tmp_path / "t.db"))
    s.add_all(
        [
            Character(name="贾宝玉", kind="story"),
            Character(name="林黛玉", kind="story"),
            Character(name="尧", kind="reference"),
        ]
    )
    s.commit()
    yield s
    s.close()


def test_state_at_defaults_all_alive(db):
    ws = state_at(db, 1)
    assert len(ws.persons) == 2  # story only
    assert all(p.alive for p in ws.persons.values())


def test_apply_event_death(db):
    ws = state_at(db, 1)
    daiyu = db.query(Character).filter(Character.name == "林黛玉").one()
    apply_event(
        db, ws,
        character_id=daiyu.id, chapter=1,
        alive=False, location="柳叶渚", status="自缢",
        note="黛玉自缢",
    )
    p = ws.person(daiyu.id)
    assert p.alive is False
    assert p.status == "自缢"
    assert "已故" in p.summary()
    # 快照落库
    snap = (
        db.query(CharacterState)
        .filter(CharacterState.character_id == daiyu.id)
        .one()
    )
    assert snap.alive is False
    assert snap.location == "柳叶渚"


def test_apply_event_no_change_skips(db):
    ws = state_at(db, 1)
    baoyu = db.query(Character).filter(Character.name == "贾宝玉").one()
    # 无实质变化（全默认）→ 不写库
    r = apply_event(db, ws, character_id=baoyu.id, chapter=1)
    assert r is None
    assert (
        db.query(CharacterState)
        .filter(CharacterState.character_id == baoyu.id)
        .count()
        == 0
    )


def test_state_at_uses_latest_snapshot(db):
    ws = state_at(db, 5)
    daiyu = db.query(Character).filter(Character.name == "林黛玉").one()
    apply_event(db, ws, character_id=daiyu.id, chapter=3, location="潇湘馆")
    # 重建 5 回状态：应读到 ch3 快照
    ws5 = state_at(db, 5)
    assert ws5.person(daiyu.id).location == "潇湘馆"
    # 重建 2 回状态：不应读到 ch3 快照
    ws2 = state_at(db, 2)
    assert ws2.person(daiyu.id).location is None
