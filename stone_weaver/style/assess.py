"""文风引擎 · 文骨检测器 v4（旁白优先）。

方法论（数据驱动校准）：
  1. 先在前80回曹雪芹原文上校准——已知正确的数据必须高分
  2. **对话/旁白分开**（用户洞察）：对话是人设强相关（刘姥姥就该白话），
     旁白才是作者文风稳定体现。检测器只对旁白段打分。
  3. 用"文言结构"而非"单字虚词"（"X之Y"定语、"者…也"判断句尾）体现文骨
  4. 实测区分度（曹雪芹 vs 癸酉本，仅旁白段）：
     - "X之Y"结构：4.74 vs 2.21（2.1x）
     - "者也矣焉兮"句尾：1.46 vs 0.17（8.6x）← 最强
     - 文白比：0.42 vs 0.21（2x）
  5. 负向：只罚真正现代痕迹（曹雪芹原文实测 ≤0.04/千 的词 + "虽然…但是"成对）
"""

from __future__ import annotations

import re

# ---- 正向：文言结构骨相 ----
# "X之Y"文言定语结构（"府中之物/园中之景"——之 作结构助词）
ZHI_STRUCT_RE = re.compile(r"[^，。！？；：、]{1,6}之[^，。！？；：、]{1,6}")
# "者…也"判断句尾 + "矣焉哉兮"文言收尾
WENYAN_END_RE = re.compile(r"[^。！？]{1,12}[者也矣焉哉兮][。！？]")
# 文言虚词（作词，非单字——"乃/遂/俄而/既而/因/故/须臾/斯"）
WENYAN_WORDS = ("乃", "遂", "俄而", "既而", "因", "故", "须臾", "斯", "是以", "因而", "自此", "及至")
# 白话语气词（文白比分母）
BAIHUA_PARTICLES = ("了", "呢", "罢", "呀", "么", "的", "着", "吧")

# ---- 负向：真现代痕迹（曹雪芹原文实测 ≤0.04/千）----
MODERN_ONLY = (
    "其实", "真的", "觉得", "认为", "进行", "关于", "对于", "突然",
    "非常", "但是", "同时", "也许", "或许", "可能", "应该", "必须",
    "竟然", "居然", "反正",
)
# "虽然…但是"成对（曹雪芹原文 0 次）
SUIRAN_DANSHI = re.compile(r"虽然[^。！？]{0,15}但是")

# 批注清洗
_ANNOT_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕.*?〔/批〕", re.S)

# 对话引号（中文“” 和 ASCII ""）
QUOTE_RE = re.compile(r"[\u201c\"]([^\u201d\"]*)[\u201d\"]")


def _clean(text: str) -> str:
    t = _ANNOT_RE.sub("", text)
    t = re.sub(r"\bverse\b", "", t)
    t = re.sub(r"^\s*题曰\s*[：:]", "", t, flags=re.M)
    return t


def split_dialogue(text: str) -> tuple[str, str]:
    """把文本拆成 (对话段, 旁白段)。

    对话 = 引号内内容 + "XX道/说/笑道："引导语；旁白 = 纯叙述。
    原理：对话是人设强相关（刘姥姥白话正常），旁白才是作者文风体现。
    """
    dialogue_parts = []
    narration_parts = []
    pos = 0
    for m in QUOTE_RE.finditer(text):
        pre = text[pos : m.start()]
        if pre.strip():
            # 引导语（"XX道："等）并入对话段
            lead = re.search(r"[^。！？]{0,20}[道说笑问答]：?$", pre)
            if lead:
                dialogue_parts.append(lead.group(0))
                before = pre[: lead.start()]
                if before.strip():
                    narration_parts.append(before)
            else:
                narration_parts.append(pre)
        dialogue_parts.append(m.group(1))
        pos = m.end()
    if pos < len(text):
        narration_parts.append(text[pos:])
    return "\n".join(dialogue_parts), "\n".join(narration_parts)


def assess(text: str, *, use_narration_only: bool = True) -> dict:
    """文骨检测。0-1 分，越高越接近曹雪芹文言骨架。

    use_narration_only=True（默认）：只对旁白段打分（对话是人设强相关，不参与）。
    """
    t = _clean(text)
    if use_narration_only:
        _, t = split_dialogue(t)
    n = len(t)
    if n < 200:
        return {"score": 0.0, "reasons": ["旁白过短（可能以对话为主）"]}

    sents = [s.strip() for s in re.split(r"[。！？\n]", t) if len(s.strip()) > 3]
    n_sents = max(len(sents), 1)

    # ---- 正向：文言骨相 ----
    # 1) "X之Y"结构密度（曹 4.74 / 癸 2.21）
    zhi = len(ZHI_STRUCT_RE.findall(t)) / n * 1000
    s_zhi = min(1.0, zhi / 4.74)  # 曹雪芹均值满格

    # 2) "者也矣焉兮"句尾密度（曹 1.46 / 癸 0.17）← 最强指标
    wenyan_end = len(WENYAN_END_RE.findall(t)) / n * 1000
    s_wenyan_end = min(1.0, wenyan_end / 1.46)

    # 3) 文言词密度（乃/遂/俄而…）
    wenyan_words = sum(t.count(w) for w in WENYAN_WORDS) / n * 1000
    s_wenyan_words = min(1.0, wenyan_words / 2.0)

    # 4) 文白比（文言虚词总量 / 白话语气词总量；曹 0.42 / 癸 0.21）
    wenyan_total = sum(t.count(w) for w in ("之", "乎", "者", "也", "矣", "焉", "哉", "兮", "其")) / n * 1000
    baihua_total = sum(t.count(w) for w in BAIHUA_PARTICLES) / n * 1000
    wb_ratio = wenyan_total / max(baihua_total, 1)
    s_ratio = min(1.0, wb_ratio / 0.42)

    # ---- 负向：真现代痕迹 ----
    modern = sum(t.count(w) for w in MODERN_ONLY) / n * 1000
    s_modern_pen = min(0.3, max(0.0, (modern - 0.8) / 0.8))  # 超曹雪芹上限(0.8)才罚
    suiran = len(SUIRAN_DANSHI.findall(t))
    s_suiran_pen = min(0.25, suiran * 0.15)

    score = max(
        0.0,
        min(
            1.0,
            0.3 * s_zhi
            + 0.35 * s_wenyan_end
            + 0.15 * s_wenyan_words
            + 0.2 * s_ratio
            - s_modern_pen
            - s_suiran_pen,
        ),
    )
    reasons = [
        f"之X结构 {zhi:.1f}/千({s_zhi:.2f})",
        f"者也句尾 {wenyan_end:.2f}/千({s_wenyan_end:.2f})",
        f"文白比 {wb_ratio:.2f}({s_ratio:.2f})",
    ]
    if modern > 0.8:
        reasons.append(f"现代虚词 {modern:.1f}/千(罚{s_modern_pen:.2f})")
    if suiran:
        reasons.append(f"虽然但是×{suiran}(罚{s_suiran_pen:.2f})")
    return {
        "score": round(score, 2),
        "n_chars": n,
        "reasons": reasons,
        "metrics": {
            "zhi_struct_per_1k": round(zhi, 1),
            "wenyan_end_per_1k": round(wenyan_end, 2),
            "wb_ratio": round(wb_ratio, 2),
            "modern_per_1k": round(modern, 1),
        },
    }


def verdict(a: dict) -> str:
    if a["score"] >= 0.55:
        return "✅ 文骨接近曹雪芹"
    if a["score"] >= 0.4:
        return "🟡 文骨尚可"
    if a["score"] >= 0.28:
        return "⚠️ 白话化倾向"
    return "❌ 文骨缺失"
