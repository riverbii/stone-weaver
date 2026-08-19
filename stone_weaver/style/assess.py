"""文风引擎 · 文风指纹评估器（题材无关）。

架构定位（docs/architecture.md §6）：
  只测"与内容无关的文体指纹"，不罚题材特征（奇幻回对话少是正常的）。

核心思路（实测验证，见 project memory [2026-08-19 文风指纹]）：
  - 正向（文言骨相）：文言虚词密度（之乎者也矣焉哉兮其若何乃遂因故则）、
    四字骈俪结构比例、文言句首率（因/遂/乃/即/俄而/忽/方）
  - 负向（白话流水账）：现代句首率（他/我/你/然后/因为/所以开头）、
    了字句尾率（以"了/着呢"收尾）、白话因果链（然后/但是/因为/所以）、
    口语堆叠（着了/的呢/的话）
  - 不罚：对话密度、动作密度（题材决定）
"""

from __future__ import annotations

import re

# ---- 文言骨相（正向）----
CLASSICAL_PARTICLES = (
    "之", "乎", "者", "也", "矣", "焉", "哉", "兮", "其", "若何",
    "乃", "遂", "因", "故", "则", "苟", "斯", "是以", "俄而", "既而", "须臾", "方",
)
WENYAN_START_RE = re.compile(r"^(因|遂|乃|即|俄而|既而|故|于是|忽|方|及|已而|须臾|自此|只因|原来)")
FOUR_CHAR_RE = re.compile(r"[^\s，。！？；：、""''（）]{4}")

# ---- 白话流水账（负向）----
# 只罚现代连词/时间词开头（然后/因为/所以/接着/后来），不罚代词（他/我/你——曹雪芹对话也用）
MODERN_START_RE = re.compile(r"^(然后|接着|但是|因为|所以|同时|后来|这时候|紧接着|随即)")
LE_END_RE = re.compile(r"(着呢|的了|了呢|过了|好了)$")
MODERN_CHAIN = ("然后", "但是", "因为", "所以", "而且", "虽然", "同时", "于是乎")
VERNACULAR_STACK = ("着了", "着呢", "的了", "了吗", "的话", "的呀", "走了过去", "走了进来")

# 批注清洗
_ANNOT_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", re.S)


def _clean(text: str) -> str:
    t = _ANNOT_RE.sub("", text)
    # 去 verse/题曰 等残留标签
    t = re.sub(r"\bverse\b", "", t)
    t = re.sub(r"^\s*题曰\s*[：:]", "", t, flags=re.M)
    return t


def assess(text: str) -> dict:
    """题材无关的文风指纹评估。0-1 分，越高越接近曹雪芹文骨。"""
    t = _clean(text)
    n = len(t)
    if n < 200:
        return {"score": 0.0, "reasons": ["文本过短"]}

    sents = [s.strip() for s in re.split(r"[。！？\n]", t) if len(s.strip()) > 3]
    n_sents = max(len(sents), 1)

    # 正向：文言骨相（题材无关——对话/奇幻/日常都有）
    classical = sum(t.count(w) for w in CLASSICAL_PARTICLES) / n * 1000
    s_classical = min(1.0, classical / 16)  # 曹雪芹 14.8-41.7，16 即高分

    fours = sum(len(m.group()) for m in FOUR_CHAR_RE.finditer(t))
    four_ratio = fours / n
    s_four = min(1.0, four_ratio / 0.65)

    # 负向：白话流水账（真正的现代痕迹）
    modern_start = sum(1 for s in sents if MODERN_START_RE.match(s)) / n_sents * 100
    s_modern_pen = min(0.3, modern_start / 20)

    le_end = sum(1 for s in sents if LE_END_RE.search(s)) / n_sents * 100
    s_le_pen = min(0.2, le_end / 30)

    chain = sum(t.count(w) for w in MODERN_CHAIN) / n * 1000
    s_chain_pen = min(0.25, chain / 6)

    vern = sum(t.count(w) for w in VERNACULAR_STACK) / n * 1000
    s_vern_pen = min(0.2, vern / 4)

    score = max(
        0.0,
        min(
            1.0,
            0.55 * s_classical
            + 0.25 * s_four
            - s_modern_pen
            - s_le_pen
            - s_chain_pen
            - s_vern_pen,
        ),
    )
    reasons = [
        f"文言虚词 {classical:.0f}/千({s_classical:.2f})",
        f"四字结构 {four_ratio:.2f}({s_four:.2f})",
    ]
    if modern_start:
        reasons.append(f"现代句首 {modern_start:.0f}%(罚{s_modern_pen:.2f})")
    if le_end:
        reasons.append(f"了字句尾 {le_end:.0f}%(罚{s_le_pen:.2f})")
    return {
        "score": round(score, 2),
        "n_chars": n,
        "reasons": reasons,
        "metrics": {
            "classical_per_1k": round(classical, 1),
            "modern_start_pct": round(modern_start, 1),
            "le_end_pct": round(le_end, 1),
            "four_char_ratio": round(four_ratio, 2),
        },
    }


def verdict(a: dict) -> str:
    if a["score"] >= 0.55:
        return "✅ 文骨接近曹雪芹"
    if a["score"] >= 0.4:
        return "🟡 文骨尚可"
    if a["score"] >= 0.28:
        return "⚠️ 白话流水账倾向"
    return "❌ 文风偏离"
