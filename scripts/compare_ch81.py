#!/usr/bin/env python3
"""对比引擎81回 vs 癸酉本真实81回（文风引擎评估）。

用法: .venv/bin/python scripts/compare_ch81.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Chapter, GeneratedChapter
from stone_weaver.style.assess import assess, verdict

# 批注标记（癸酉本〔批:xx〕…〔/批〕）
ANNOT_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", re.S)
PREFACE_RE = re.compile(r"\[批语[:：]|回前批|此回")


def clean(text: str) -> str:
    """剥离批注标记，返回纯正文。"""
    t = ANNOT_RE.sub("", text)
    return t


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    real = db.query(Chapter).filter(Chapter.version == "guihui_v3", Chapter.num == 81).first()
    # 取最新的引擎版本（可能有多次生成）
    eng = (
        db.query(GeneratedChapter)
        .filter(GeneratedChapter.num == 81)
        .order_by(GeneratedChapter.id.desc())
        .first()
    )

    real_clean = clean(real.content)
    eng_text = eng.content

    print("=" * 60)
    print(f"癸酉本真实81回: 原始 {len(real.content)} 字 → 剥批后 {len(real_clean)} 字")
    print(f"引擎81回:       {len(eng_text)} 字")
    print("=" * 60)

    # 整体评估（真实回取正文前 3000 字对齐长度）
    real_sample = real_clean[:3000]
    a_real = assess(real_sample)
    a_eng = assess(eng_text)
    print("\n【文风评估（全文分——受拼接过渡影响，仅供参考）】")
    print(f"  癸酉本真实: score={a_real['score']} {verdict(a_real)}")
    print(f"  引擎:       score={a_eng['score']} {verdict(a_eng)}")

    # 分段评估（每 500 字一段分别评分取平均——更准）
    def seg_avg(text: str, seg_len: int = 500) -> float:
        scores = []
        for i in range(0, len(text), seg_len):
            chunk = text[i : i + seg_len]
            if len(chunk) < 100:
                continue
            scores.append(assess(chunk)["score"])
        return sum(scores) / len(scores) if scores else 0

    print("\n【文风评估（分段均分——主指标）】")
    print(f"  癸酉本真实: 段均分 {seg_avg(real_sample):.2f}")
    print(f"  引擎:       段均分 {seg_avg(eng_text):.2f}")

    # 分段评估（各取 3 段各 500 字）
    print("\n【分段抽样（3 段 × 500 字）】")
    for label, text in [("癸酉本真实", real_sample), ("引擎", eng_text)]:
        lens = [len(s) for s in text.split("。") if len(s) > 30]
        scores = []
        for chunk in [text[i : i + 500] for i in range(0, min(len(text), 3000), 800)]:
            if len(chunk) < 100:
                continue
            scores.append(assess(chunk)["score"])
        avg = sum(scores) / len(scores) if scores else 0
        print(f"  {label}: 段均分 {avg:.2f}（{len(scores)} 段）")

    # 简单句法指标
    print("\n【句法指标】")
    for label, text in [("癸酉本真实", real_sample), ("引擎", eng_text)]:
        sents = [s for s in re.split(r"[。！？\n]", text) if len(s) > 5]
        lens = [len(s) for s in sents]
        avg_len = sum(lens) / len(lens) if lens else 0
        max_len = max(lens) if lens else 0
        quote_density = text.count("“") / max(len(text), 1) * 100
        print(f"  {label}: 句数 {len(sents)} | 均句长 {avg_len:.1f} | 最长 {max_len} | 引号密度 {quote_density:.2f}/百字")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
