#!/usr/bin/env python3
"""题曰诗格律校验：平仄/押韵/对仗（LLM 判定，懂近体诗格律）。

用法:
  .venv/bin/python scripts/check_tiyu_geilv.py                # 引擎版 28 回
  .venv/bin/python scripts/check_tiyu_geilv.py --original     # 癸酉本原文 28 回对比
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.llm import LLMClient
from stone_weaver.models import Chapter, GeneratedChapter

CHECK_PROMPT = """你是近体诗格律专家。请校验下面这首诗的格律（平仄、押韵、对仗、黏对）。

诗作：
{poem}

请只输出 JSON：
{{"pingze_ok": true/false, "issue": "平仄问题具体说明，无则空", "rhyme_ok": true/false, "rhyme_issue": "押韵问题，无则空", "duizhang_ok": true/false, "duizhang_issue": "对仗问题，无则空", "grade": "A/B/C/D(格律质量)", "note": "一句总评"}}

要求：
- 按近体诗规则判断（七言绝句/律诗：平仄相间、押平声韵、颔联颈联对仗）
- 癸酉本是明清白话小说开篇诗，格律可能不严，宽容判断但指出问题
- 只评格律，不评内容意境
"""


def extract_poem(text: str) -> str:
    """从回目内容提取题曰诗。"""
    m = re.search(r"题曰[：:]\s*\n?(.*?)(?:\n\n|\n话说|\nverse)", text, re.S)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"题曰[：:]\s*([^\n]+)", text)
    return m2.group(1).strip() if m2 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", action="store_true", help="评癸酉本原文而非引擎版")
    args = ap.parse_args()

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    client = LLMClient()
    results = {}

    for num in range(81, 109):
        if args.original:
            ch = db.query(Chapter).filter(Chapter.version=="guihui_v3", Chapter.num==num).first()
            text = ch.content
        else:
            g = db.query(GeneratedChapter).filter(GeneratedChapter.num==num).first()
            if g is None:
                continue
            text = g.content
        poem = extract_poem(text)
        if not poem:
            print(f"ch{num}: 无题曰", flush=True)
            continue
        raw = client.chat(
            [{"role": "system", "content": CHECK_PROMPT.replace("{poem}", poem[:200])}],
            temperature=0.1,
        )
        s = raw.strip()
        a, b = s.find("{"), s.rfind("}")
        if a == -1 or b <= a:
            print(f"ch{num}: 解析失败", flush=True)
            continue
        try:
            data = json.loads(s[a : b + 1])
        except Exception:
            print(f"ch{num}: JSON失败", flush=True)
            continue
        data["poem"] = poem.replace("\n", " / ")
        results[str(num)] = data
        print(f"ch{num}: {data.get('grade','?')} 平仄{'✅' if data.get('pingze_ok') else '❌'} 押韵{'✅' if data.get('rhyme_ok') else '❌'} 对仗{'✅' if data.get('duizhang_ok') else '❌'} | {poem[:28]}", flush=True)

    label = "original" if args.original else "engine"
    out = ROOT / "data" / f"tiyu_geilv_{label}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    # 汇总
    grades = {}
    for v in results.values():
        grades[v.get("grade", "?")] = grades.get(v.get("grade", "?"), 0) + 1
    print(f"\n格律分布: {grades}")
    print(f"报告: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
