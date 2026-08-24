#!/usr/bin/env python3
"""物化"自家版本"：把 81-108 每回的选定来源固化为 chapters 表的 version=self。

核心思想（用户决策）："用原文还是引擎"是内容编辑决策，应在内容准备阶段
定稿为实体数据，而不是部署/路由阶段动态判断。

选稿规则（来自 data/guihui_judge_report.json，LLM 纯文笔裁判）：
  - score ≥ 6：用癸酉本原文（guihui_clean）
  - score < 6：用引擎重建（generated_chapters）
来源标注存入 title 后缀（不污染正文），正文内容物化。

用法:
  .venv/bin/python scripts/materialize_self.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Chapter, GeneratedChapter


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))

    # 1. 选稿决策
    report_path = ROOT / "data" / "guihui_judge_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    use_original = {
        int(k) for k, v in report.items()
        if isinstance(v, dict) and v.get("score") is not None and v["score"] >= 6
    }

    # 2. 物化：逐回取选定来源，构建 version=self 章节
    rows = []
    for num in range(81, 109):
        if num in use_original:
            src = db.query(Chapter).filter(
                Chapter.version == "guihui_clean", Chapter.num == num
            ).first()
            source_label = "癸酉本原文"
        else:
            src = db.query(GeneratedChapter).filter(
                GeneratedChapter.num == num
            ).first()
            source_label = "引擎重建"
        if src is None:
            print(f"⚠️ ch{num} 无内容（{source_label}），跳过", flush=True)
            continue
        title = f"{src.title}　〔{source_label}〕" if source_label == "引擎重建" else src.title
        rows.append(
            {
                "num": num,
                "title": title,
                "version": "self",
                "content": src.content,
                "source": source_label,
            }
        )

    # 3. 覆盖写入（幂等：删旧 self 版本）
    db.query(Chapter).filter(Chapter.version == "self").delete()
    for r in rows:
        db.add(
            Chapter(
                num=r["num"],
                title=r["title"],
                version=r["version"],
                content=r["content"],
            )
        )
    db.commit()

    # 4. 固化选稿决策（供前端/统计用）
    decision = {
        str(num): ("original" if num in use_original else "engine")
        for num in range(81, 109)
    }
    (ROOT / "data" / "self_decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"✅ 自家版本物化完成：{len(rows)} 回（version=self）")
    print(f"   原文 {sum(1 for r in rows if r['source']=='癸酉本原文')} 回 + "
          f"引擎 {sum(1 for r in rows if r['source']=='引擎重建')} 回")
    print(f"   选稿决策已存 data/self_decision.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
