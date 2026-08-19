#!/usr/bin/env python3
"""前80回文风基线统计：建立"曹雪芹文风"的量化参照系。

用途：
  1. 校准文风检测器（当前黑名单有误报：因/遂/乃/便等被当现代词）
  2. 给生成器提供精确的风格目标（动作词密度/句长/对话比例的真实分布）
  3. 后续任何生成文本可与基线对比打分

输出：
  - stdout：整体基线 + 分回抽样
  - data/style_baseline.json：持久化基线（供 assess 使用）
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

# 动作白描词（曹雪芹推进叙事用）
ACTION_WORDS = (
    "起身", "上前", "拉住", "拦住", "扯", "夺", "跪", "摔", "啐", "抢",
    "拽", "一把", "登时", "忙", "便", "回身", "转身", "低头", "抬头",
    "笑道", "说道", "问道", "答道", "哭道", "叹道", "喝道", "叫道",
)
# 过渡词
MARKERS = ("话说", "这日", "只见", "当下", "一时", "因", "遂", "乃", "且说", "次日", "于是")
# 语气词
PARTICLES = ("了", "呢", "罢", "呀", "么", "不成")
# 待校准的"疑似现代词"——先在原文统计出现情况
SUSPECT_MODERN = (
    "然后", "因为", "所以", "但是", "突然", "非常", "觉得", "自己", "我们",
    "他们", "来说", "其实", "真的", "有点", "仿佛", "似乎", "如同", "好像",
    "被", "的的确",
)
# 抒情/景物收尾特征（观察曹雪芹用不用）
LYRICAL = ("仿佛", "似乎", "唯余", "唯有", "恍如", "恰似", "犹如")


def stats(text: str) -> dict:
    t = re.sub(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", "", text, flags=re.S)
    t = re.sub(r"〔批(?:[:：][^〕]*)?〕", "", t)
    t = re.sub(r"〔/批〕", "", t)
    n = len(t)
    sents = [s for s in re.split(r"[。！？；\n]", t) if len(s.strip()) > 3]
    quotes = t.count("“")
    return {
        "chars": n,
        "sentences": len(sents),
        "avg_sent_len": round(n / max(len(sents), 1), 1),
        "action_per_1k": round(sum(t.count(w) for w in ACTION_WORDS) / n * 1000, 1),
        "marker_per_1k": round(sum(t.count(m) for m in MARKERS) / n * 1000, 1),
        "particle_per_1k": round(sum(t.count(p) for p in PARTICLES) / n * 1000, 1),
        "quote_per_1k": round(quotes / n * 1000, 1),
        "lyrical_per_1k": round(sum(t.count(w) for w in LYRICAL) / n * 1000, 2),
        "bei_per_1k": round(len(re.findall(r"被[^。！？，]{1,10}", t)) / n * 1000, 2),
    }


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    all_stats = []
    rows = []
    for ch in (
        db.query(Chapter)
        .filter(Chapter.version == "gongban_rb")
        .order_by(Chapter.num)
        .all()
    ):
        s = stats(ch.content)
        s["chapter"] = ch.num
        all_stats.append(s)
        rows.append(s)

    # 聚合（忽略空回）
    valid = [s for s in all_stats if s["chars"] > 5000]
    agg = {
        k: round(sum(s[k] for s in valid) / len(valid), 2)
        for k in ("avg_sent_len", "action_per_1k", "marker_per_1k",
                  "particle_per_1k", "quote_per_1k", "lyrical_per_1k", "bei_per_1k")
    }
    agg["n_chapters"] = len(valid)

    print("=" * 64)
    print("前80回文风基线（gongban_rb，去批注后统计，每千字密度）")
    print("=" * 64)
    for k, v in agg.items():
        print(f"  {k:18s}: {v}")
    print()
    print("分回抽样（每 10 回）：")
    for s in rows:
        if s["chapter"] % 10 == 1:
            print(
                f"  第{s['chapter']:2d}回: 句长{s['avg_sent_len']:5.1f} "
                f"动作{s['action_per_1k']:5.1f} 对话{s['quote_per_1k']:5.1f} "
                f"抒情{s['lyrical_per_1k']:5.2f} 被字{s['bei_per_1k']:5.2f}"
            )

    # 疑似现代词在原文中的真实出现（判断黑名单是否误报）
    print()
    print("疑似现代词在原文的实际密度（/千字）：")
    text_all = "".join(c.content for c in db.query(Chapter).filter(Chapter.version == "gongban_rb").all())
    text_all = re.sub(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", "", text_all, flags=re.S)
    for w in SUSPECT_MODERN:
        cnt = text_all.count(w)
        print(f"  {w}: {cnt} 次 ({cnt/max(len(text_all),1)*1000:.2f}/千字)")

    # 持久化
    out = ROOT / "data" / "style_baseline.json"
    payload = {"baseline": agg, "per_chapter": rows, "note": "gongban_rb 前80回文风基线"}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已保存基线: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
