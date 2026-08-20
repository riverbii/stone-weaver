"""文风引擎 · 套路词检测（生成后自动把关）。

检测 LLM 生成的"古风套路词"是否超量。基于曹雪芹前80回实测基线：
  - 曹雪芹 71 万字中这些词几乎不用（0-30次）
  - LLM 生成常过量 10-80 倍

用途：simulate_one_beat 生成后调用，超量则提示重生成/人工修正。
"""

from __future__ import annotations

import re

# 套路词 → 每万字限量（校准：曹雪芹 22次/71万字≈0.3/万字；
# 模型实测能压到 ~12-15/1.5万字，取 8/万字 作硬限）
CLICHE_LIMITS = {
    "半晌": 8,
    "怔了": 4,
    "眼圈": 4,
    "哽咽": 2,
    "喉头": 2,
    "说不出话": 2,
    "好半晌": 1,
    "半晌方": 2,
    "忽然": 8,
    "微微": 5,
    "默默": 3,
    "静静": 3,
    "心头": 4,
    "长叹": 4,
    "不由得": 3,
    "暗自": 3,
}


def check_cliches(text: str) -> list[str]:
    """返回超量的套路词报告。空列表 = 通过。限量按 1 万字归一化。"""
    scale = max(len(text), 1) / 10000  # 1 万字 = 1.0
    problems = []
    for word, limit in CLICHE_LIMITS.items():
        n = text.count(word)
        if n > limit * scale:
            problems.append(f"「{word}」出现 {n} 次（1万字限量 {limit}，曹雪芹几乎不用）")
    return problems


def check_patterns(text: str) -> list[str]:
    """句式模式检查：'X听了'密度、'话说'数量。限量按 1 万字归一化。"""
    scale = max(len(text), 1) / 10000
    problems = []
    ting = len(re.findall(r"[\u4e00-\u9fff]{1,4}听了", text))
    if ting > 16 * scale:  # 模型实测 ~15-21/1.5万字，取 16/万字
        problems.append(f"「X听了」出现 {ting} 次（1万字限量 16）")
    hua = text.count("话说")
    if hua > 4 * scale:
        problems.append(f"「话说」出现 {hua} 次（1万字限量 4）")
    return problems


def check_style(text: str) -> list[str]:
    """综合文风套路检查。返回超量问题列表。"""
    return check_cliches(text) + check_patterns(text)
