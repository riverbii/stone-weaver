"""文风引擎 · 自动评估。

架构定位（docs/architecture.md §6）：输出 vs 前80回基线的轻量自动指标，
人工终审为准。指标：
  - 句长分布（中位句长、长短句比例）——曹雪芹句式长于现代文
  - 虚词/语气词频率（了/呢/罢/呀）——白话程度
  - 章回体过渡词出现（话说/这日/只见/当下/一时）
  - 现代词检出（"的"高密度/明显现代词汇）——负向信号
"""

from __future__ import annotations

import re

from collections import Counter

# 现代高频词（负向信号，出现即扣分）
MODERN_WORDS = (
    "的的确", "然后", "因为", "所以", "但是", "突然", "非常", "觉得",
    "自己", "我们", "他们", "这的", "来说", "其实", "真的", "有点",
)
# 章回体过渡词（正向信号）
CLASSICAL_MARKERS = ("话说", "这日", "只见", "当下", "一时", "因", "遂", "乃", "且说", "次日", "于是")
# 白话语气词（曹雪芹文中常见）
PARTICLES = ("了", "呢", "罢", "呀", "么", "不成")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？；\n]", text)
    return [p.strip() for p in parts if p.strip()]


def assess(text: str) -> dict:
    """返回文风评估指标（0-1 分制，越高越像前80回风格）。"""
    sents = _sentences(text)
    if not sents:
        return {"score": 0.0, "n_sentences": 0, "reasons": ["无内容"]}

    lens = [len(s) for s in sents]
    median_len = sorted(lens)[len(lens) // 2]

    # 1. 句长：曹雪芹段落中位句长一般 15-40 字（现代中文约 10-20）
    len_score = 0.5 if 12 <= median_len <= 45 else (0.3 if median_len > 8 else 0.2)

    # 2. 过渡词密度（每 100 字出现数）
    marker_hits = sum(text.count(m) for m in CLASSICAL_MARKERS)
    marker_density = marker_hits / max(len(text), 1) * 100
    marker_score = min(1.0, marker_density * 6)

    # 3. 语气词密度
    particle_hits = sum(text.count(p) for p in PARTICLES)
    particle_density = particle_hits / max(len(text), 1) * 100
    particle_score = min(1.0, particle_density * 4)

    # 4. 现代词负向
    modern_hits = sum(text.count(w) for w in MODERN_WORDS)
    modern_penalty = min(0.4, modern_hits * 0.05)

    score = max(
        0.0,
        min(1.0, 0.25 * len_score + 0.3 * marker_score + 0.25 * particle_score - modern_penalty),
    )
    reasons = [
        f"中位句长 {median_len} 字" + ("（偏短，可能太白话）" if median_len < 12 else ""),
        f"章回过渡词 {marker_hits} 次/千字",
        f"语气词 {particle_hits} 次",
    ]
    if modern_hits:
        reasons.append(f"现代词 {modern_hits} 次（负向）")
    return {
        "score": round(score, 2),
        "n_sentences": len(sents),
        "median_len": median_len,
        "reasons": reasons,
    }


def verdict(a: dict) -> str:
    if a["score"] >= 0.45:
        return "✅ 文风达标"
    if a["score"] >= 0.35:
        return "🟡 文风接近，需润色"
    return "❌ 文风不符，需重写"
