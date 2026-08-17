#!/usr/bin/env python3
"""阶段2 试点：单 beat 文风生成 + 校验（验证"生成像不像曹雪芹"）。

用法:
  .venv/bin/python scripts/trial_generate.py
  .venv/bin/python scripts/trial_generate.py --persist   # 落库验证

先用前80回内的简单 beat（无情节压力）验证文风；通过后再接后28回情节弧。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.engine.simulate import simulate_one_beat
from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.style.anchors import extract_anchors
from stone_weaver.style.assess import assess, verdict
from stone_weaver.world.state import state_at


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persist", action="store_true", help="落库（events/generated_chapters）")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    client = LLMClient()

    # 前80回锚点（少量即可，控制 token）
    anchors = extract_anchors(db, chapters=list(range(1, 41)), per_kind=2)
    print(f"风格锚点: {len(anchors)} 条")
    state = state_at(db, 20)  # 第20回左右的世界状态（人物都在世）

    # 无情节压力的简单 beat：大观园日常
    beat = {
        "scene": "大观园沁芳桥畔",
        "goal": "宝玉与黛玉在沁芳桥畔闲谈，论及落花，黛玉伤感，宝玉以痴语劝解",
        "characters": ["宝玉", "黛玉"],
        "constraints": ["时值暮春", "二人均在世"],
        "expected_out": "二人关系如故",
    }

    result = simulate_one_beat(
        db,
        client,
        beat,
        state,
        anchors,
        chapter_num=20,
        title="【试点】沁芳桥畔",
        persist=args.persist,
    )
    print("\n" + "=" * 50)
    if result["ok"]:
        print("✅ 生成成功，重试次数:", result["retries"])
        print("\n--- 生成正文 ---")
        print(result["text"][:1500])
        a = assess(result["text"])
        print("\n--- 文风评估 ---")
        print(f"score={a['score']} {verdict(a)}")
        for r in a["reasons"]:
            print("  ·", r)
        if result["violations"]:
            print("\n--- 校验提示 ---")
            for v in result["violations"]:
                print(f"  [{v.severity}] {v.message}")
    else:
        print("❌ 生成失败（重试后仍无结果）")
        for v in result["violations"]:
            print(f"  [{v.severity}] {v.message}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
