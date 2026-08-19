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
# 现代抒情腔（负向信号，大扣分）——"被…照着/仿佛…罢了/唯余…"式散文腔
MODERN_LYRICAL = (
    "仿佛", "似乎", "如同", "宛如", "不过…罢了", "唯余", "唯有", "唯有那",
    "被…照着", "被…拉着", "被…拦住", "恰似", "好像", "犹如", "恍如", "如梦似幻",
)
# 被字句（现代汉语标志，古文极少用）
BEI_RE = re.compile(r"被[^。！？，]{1,12}[着住了拉住拦]")
# 章回体过渡词（正向信号）
CLASSICAL_MARKERS = ("话说", "这日", "只见", "当下", "一时", "因", "遂", "乃", "且说", "次日", "于是")
# 白话语气词（曹雪芹文中常见）
PARTICLES = ("了", "呢", "罢", "呀", "么", "不成")
# 动作白描词（正向信号——曹雪芹靠动作推进）
ACTION_WORDS = ("起身", "上前", "拉住", "拦住", "扯", "夺", "跪", "摔", "啐", "抢", "拽", "一把", "登时", "忙", "便", "回身", "转身", "低头", "抬头")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？；\n]", text)
    return [p.strip() for p in parts if p.strip()]


def assess(text: str) -> dict:
    """返回文风评估指标（0-1 分制，越高越像曹雪芹叙事文风）。

    指标：句长、过渡词、语气词、动作词（正向）、现代词/抒情腔/被字句（负向）。
    """
    sents = _sentences(text)
    if not sents:
        return {"score": 0.0, "n_sentences": 0, "reasons": ["无内容"]}

    lens = [len(s) for s in sents]
    median_len = sorted(lens)[len(lens) // 2]

    # 1. 句长：曹雪芹段落中位句长一般 15-40 字
    len_score = 0.5 if 12 <= median_len <= 45 else (0.3 if median_len > 8 else 0.2)

    # 2. 过渡词密度
    marker_hits = sum(text.count(m) for m in CLASSICAL_MARKERS)
    marker_density = marker_hits / max(len(text), 1) * 100
    marker_score = min(1.0, marker_density * 6)

    # 3. 语气词密度
    particle_hits = sum(text.count(p) for p in PARTICLES)
    particle_density = particle_hits / max(len(text), 1) * 100
    particle_score = min(1.0, particle_density * 4)

    # 4. 动作词密度（正向——曹雪芹靠动作推进）
    action_hits = sum(text.count(w) for w in ACTION_WORDS)
    action_density = action_hits / max(len(text), 1) * 100
    action_score = min(1.0, action_density * 8)

    # 5. 现代词负向
    modern_hits = sum(text.count(w) for w in MODERN_WORDS)
    modern_penalty = min(0.3, modern_hits * 0.03)

    # 6. 现代抒情腔负向（大扣分——"仿佛…罢了"式散文腔）
    lyrical_hits = 0
    for w in MODERN_LYRICAL:
        if "…" in w:
            a, b = w.split("…")
            lyrical_hits += len(re.findall(re.escape(a) + r"[^。！？]{0,12}" + re.escape(b), text))
        else:
            lyrical_hits += text.count(w)
    lyrical_penalty = min(0.4, lyrical_hits * 0.1)

    # 7. 被字句负向
    bei_hits = len(BEI_RE.findall(text))
    bei_penalty = min(0.2, bei_hits * 0.05)

    score = max(
        0.0,
        min(
            1.0,
            0.2 * len_score
            + 0.2 * marker_score
            + 0.15 * particle_score
            + 0.2 * action_score
            - modern_penalty
            - lyrical_penalty
            - bei_penalty,
        ),
    )
    reasons = [
        f"中位句长 {median_len} 字",
        f"动作词 {action_hits} 次",
        f"章回过渡词 {marker_hits} 次",
    ]
    if modern_hits:
        reasons.append(f"现代词 {modern_hits} 次（负向）")
    if lyrical_hits:
        reasons.append(f"抒情腔 {lyrical_hits} 次（负向）")
    if bei_hits:
        reasons.append(f"被字句 {bei_hits} 次（负向）")
    return {
        "score": round(score, 2),
        "n_sentences": len(sents),
        "median_len": median_len,
        "reasons": reasons,
    }


def verdict(a: dict) -> str:
    if a["score"] >= 0.45:
        return "✅ 文风达标"
    if a["score"] >= 0.32:
        return "🟡 文风接近，需润色"
    return "❌ 文风不符，需重写"
