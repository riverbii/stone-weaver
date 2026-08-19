#!/usr/bin/env python3
"""癸酉本后28回（81-108）文风逐回评估。

用途：判断哪些回文风已接近曹雪芹（可直接用原文），哪些回文风差（需引擎重建）。

基准：曹雪芹前80回实测基线（style_baseline.py 生成）。
输出：每回分数 + verdict + 分维度指标，落盘 data/guihui_style_report.json。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Chapter
from stone_weaver.style.assess import assess, verdict

ANNOT_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", re.S)


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    rows = []
    for ch in (
        db.query(Chapter)
        .filter(Chapter.version == "guihui_v3", Chapter.num.between(81, 108))
        .order_by(Chapter.num)
        .all()
    ):
        text = ANNOT_RE.sub("", ch.content)
        a = assess(text)
        rows.append(
            {
                "num": ch.num,
                "title": ch.title,
                "chars": len(text),
                "score": a["score"],
                "verdict": verdict(a),
                "metrics": a.get("metrics", {}),
                "reasons": a["reasons"],
            }
        )

    # 排序输出
    print("=" * 76)
    print("癸酉本后28回文风评估（对照曹雪芹前80回基线）")
    print("=" * 76)
    print(f"{'回':>3} {'分数':>5}  判定            均句长  动作/千  对话/千  抒情/千  被字/千")
    print("-" * 76)
    for r in sorted(rows, key=lambda r: -r["score"]):
        m = r["metrics"]
        print(
            f"{r['num']:>3} {r['score']:>5.2f}  {r['verdict']:<12} "
            f"{m.get('avg_sent_len',0):>5} {m.get('action_per_1k',0):>6} "
            f"{m.get('quote_per_1k',0):>6} {m.get('lyrical_per_1k',0):>6.2f} "
            f"{m.get('bei_per_1k',0):>6.2f}  {r['title'][:24]}"
        )

    # 分组统计
    usable = [r for r in rows if r["score"] >= 0.55]   # 文风接近 → 可直接用
    borderline = [r for r in rows if 0.45 <= r["score"] < 0.55]
    bad = [r for r in rows if r["score"] < 0.45]        # 文风差 → 需重建
    print("\n" + "=" * 76)
    print(f"✅ 文风接近曹雪芹（可直接用原文）: {len(usable)} 回 → {[r['num'] for r in usable]}")
    print(f"🟡 文风尚可（可参考/微调）: {len(borderline)} 回 → {[r['num'] for r in borderline]}")
    print(f"❌ 文风偏差明显（需引擎重建）: {len(bad)} 回 → {[r['num'] for r in bad]}")
    print(f"\n整体均值: {sum(r['score'] for r in rows)/len(rows):.2f}")

    # 落盘
    out = ROOT / "data" / "guihui_style_report.json"
    out.write_text(
        json.dumps({"rows": rows, "usable": [r["num"] for r in usable],
                    "borderline": [r["num"] for r in borderline],
                    "bad": [r["num"] for r in bad]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n报告已保存: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
