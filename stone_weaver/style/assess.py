"""文风引擎 · 基线校准评估器。

架构定位（docs/architecture.md §6）：
  - 基于前80回实测基线（data/style_baseline.json）计算"偏离度"，
    而不是拍脑袋黑名单。
  - 指标：句长、动作词密度、对话密度、语气词密度、抒情词密度、被字句密度。
  - 曹雪芹基线实测（gongban_rb 前80回）：
      avg_sent_len 23.6 | action 11.7/千 | quote 12.4/千 | particle 27.2/千
      lyrical 0.03/千 | bei 0.26/千
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 前80回实测基线（scripts/style_baseline.py 生成）
_BASELINE = {
    "avg_sent_len": 23.55,
    "action_per_1k": 11.68,
    "quote_per_1k": 12.40,
    "particle_per_1k": 27.19,
    "lyrical_per_1k": 0.03,
    "bei_per_1k": 0.26,
}

ACTION_WORDS = (
    "起身", "上前", "拉住", "拦住", "扯", "夺", "跪", "摔", "啐", "抢",
    "拽", "一把", "登时", "忙", "便", "回身", "转身", "低头", "抬头",
    "笑道", "说道", "问道", "答道", "哭道", "叹道", "喝道", "叫道",
)
PARTICLES = ("了", "呢", "罢", "呀", "么", "不成")
LYRICAL = ("仿佛", "似乎", "唯余", "唯有那", "恍如", "恰似", "犹如", "好像", "如同", "宛如")
BEI_RE = re.compile(r"被[^。！？，]{1,10}")


def _clean(text: str) -> str:
    t = re.sub(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", "", text, flags=re.S)
    return t


def _per_1k(text: str, words) -> float:
    return sum(text.count(w) for w in words) / max(len(text), 1) * 1000


def _ratio(actual: float, target: float, tolerance: float) -> float:
    """偏离度 → 0-1 分。在 tolerance 内满分，偏离越远越低。

    tolerance 为**相对偏离比例**（如 0.5 = 允许 ±50%）。
    """
    if target == 0:
        return 1.0 if actual <= tolerance else max(0.0, 1.0 - (actual - tolerance) / tolerance)
    diff = abs(actual - target) / max(target, 1e-9)
    return max(0.0, 1.0 - diff / tolerance)


def _ratio_abs(actual: float, target: float, abs_tol: float) -> float:
    """用**绝对差**衡量偏离（适合被字句/抒情这类目标≈0 或波动小的指标）。"""
    diff = abs(actual - target)
    return max(0.0, 1.0 - diff / abs_tol)


def assess(text: str) -> dict:
    """基线校准评估：0-1 分，越高越接近曹雪芹前80回文风。"""
    t = _clean(text)
    n = len(t)
    if n < 100:
        return {"score": 0.0, "reasons": ["文本过短"]}

    sents = [s for s in re.split(r"[。！？；\n]", t) if len(s.strip()) > 3]
    avg_len = n / max(len(sents), 1)
    action = _per_1k(t, ACTION_WORDS)
    quote = t.count("“") / n * 1000
    particle = _per_1k(t, PARTICLES)
    lyrical = _per_1k(t, LYRICAL)
    bei = len(BEI_RE.findall(t)) / n * 1000

    # 各维度与基线比值（容差：句长 40%，动作 100%，对话 50%，语气词 80%）
    s_len = _ratio(avg_len, _BASELINE["avg_sent_len"], 0.40)
    s_action = _ratio(action, _BASELINE["action_per_1k"], 1.00)
    s_quote = _ratio(quote, _BASELINE["quote_per_1k"], 0.50)
    s_particle = _ratio(particle, _BASELINE["particle_per_1k"], 0.80)
    # 抒情与被字句：绝对容差（曹雪芹几乎不用，允许 ±0.3/千 的统计噪声）
    s_lyrical = _ratio_abs(lyrical, _BASELINE["lyrical_per_1k"], 0.3)
    s_bei = _ratio_abs(bei, _BASELINE["bei_per_1k"], 0.3)

    score = (
        0.25 * s_len
        + 0.1 * s_action
        + 0.2 * s_quote
        + 0.05 * s_particle
        + 0.25 * s_lyrical
        + 0.15 * s_bei
    )
    reasons = [
        f"均句长 {avg_len:.0f}字(基线23.6, {s_len:.2f})",
        f"动作词 {action:.0f}/千(基线11.7, {s_action:.2f})",
        f"对话 {quote:.0f}/千(基线12.4, {s_quote:.2f})",
        f"抒情 {lyrical:.2f}/千(基线0.03, {s_lyrical:.2f})",
        f"被字句 {bei:.2f}/千(基线0.26, {s_bei:.2f})",
    ]
    return {
        "score": round(score, 2),
        "n_chars": n,
        "reasons": reasons,
        "metrics": {
            "avg_sent_len": round(avg_len, 1),
            "action_per_1k": round(action, 1),
            "quote_per_1k": round(quote, 1),
            "lyrical_per_1k": round(lyrical, 2),
            "bei_per_1k": round(bei, 2),
        },
    }


def verdict(a: dict) -> str:
    if a["score"] >= 0.6:
        return "✅ 文风接近曹雪芹"
    if a["score"] >= 0.45:
        return "🟡 文风尚可，需润色"
    if a["score"] >= 0.3:
        return "⚠️ 文风偏现代，需重写"
    return "❌ 文风不符"
