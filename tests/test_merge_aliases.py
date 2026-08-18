"""别名归并器测试（防止 canonical 选择回归）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from merge_aliases import apply, find_groups  # noqa: E402

from stone_weaver.ingest.text import make_engine, make_session  # noqa: E402
from stone_weaver.models import Base, Character  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    s = make_session(str(tmp_path / "t.db"))
    yield s
    s.close()


def test_daiyu_group_canonical_is_lindaiyu(db):
    """黛玉组 canonical 必须是"林黛玉"（带姓氏标准全名），不是"潇湘妃子"。"""
    db.add_all(
        [
            Character(name="林黛玉", aliases=["黛玉", "林妹妹"], kind="story"),
            Character(name="黛玉", aliases=["林黛玉", "颦儿"], kind="story"),
            Character(name="潇湘妃子", aliases=["黛玉", "林黛玉"], kind="story"),
        ]
    )
    db.commit()
    n = apply(db)
    assert n == 2
    remaining = {c.name for c in db.query(Character).all()}
    assert remaining == {"林黛玉"}
    daiyu = db.query(Character).filter(Character.name == "林黛玉").one()
    assert "黛玉" in daiyu.aliases
    assert "潇湘妃子" in daiyu.aliases


def test_zhen_baoyu_never_merges_with_baoyu(db):
    """甄宝玉是独立人物，绝不能与贾宝玉/宝玉合并。"""
    db.add_all(
        [
            Character(name="贾宝玉", aliases=["宝玉", "宝二爷"], kind="story"),
            Character(name="宝玉", aliases=["贾宝玉"], kind="story"),
            Character(name="甄宝玉", aliases=["宝玉"], kind="story"),
        ]
    )
    db.commit()
    apply(db)
    names = {c.name for c in db.query(Character).all()}
    assert "甄宝玉" in names  # 甄宝玉独立保留
    assert "贾宝玉" in names  # 贾宝玉为 canonical


def test_single_char_alias_not_chain(db):
    """单字别名（玉）不得把含"玉"的人物串成一个组。"""
    db.add_all(
        [
            Character(name="贾宝玉", aliases=["宝玉", "玉"], kind="story"),
            Character(name="林黛玉", aliases=["黛玉", "玉"], kind="story"),
            Character(name="妙玉", aliases=["玉"], kind="story"),
        ]
    )
    db.commit()
    groups = find_groups(db)
    # 单字别名被过滤，不应产生跨人物大组
    assert all(len(g) == 1 for g in groups) or all(
        len({c.name for c in g}) <= 2 for g in groups
    )


def test_kinship_name_not_merged_into_group(db):
    """'林黛玉之母'是亲属称谓，不应并入黛玉组。"""
    db.add_all(
        [
            Character(name="林黛玉", aliases=["黛玉"], kind="story"),
            Character(name="黛玉", aliases=["林黛玉"], kind="story"),
            Character(name="林黛玉之母", aliases=["贾敏"], kind="story"),
        ]
    )
    db.commit()
    apply(db)
    names = {c.name for c in db.query(Character).all()}
    assert "林黛玉" in names
    assert "林黛玉之母" in names  # 亲属称谓保留为独立记录
