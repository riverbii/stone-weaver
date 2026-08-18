"""文风引擎 · 文风 prompt 组装与生成调用。

架构定位（docs/architecture.md §6）：
  - 不做模型微调，用前80回锚点做 few-shot 风格约束
  - 输出评估在 style/assess.py（自动指标）＋ 人工终审
  - 本模块提供：build_style_prompt（把锚点+状态+目标拼成生成 prompt）
"""

from __future__ import annotations

import re

from ..llm import LLMClient
from ..world.state import WorldState
from .anchors import StyleAnchor, format_anchors

# 模型输出残留标记（如 <｜end▁of▁sentence｜> / <end_of_turn> 等）
_JUNK_RE = re.compile(r"<\|?end▁of▁sentence\|?>|<end_of_turn>|<\|?im_end\|?>", re.I)


def _clean_output(text: str) -> str:
    return _JUNK_RE.sub("", text).strip()

SCENE_PROMPT = """你是一位深谙《红楼梦》文风的续写专家。请根据给定的"世界状态"与"场景目标"，用曹雪芹的笔法写一段小说正文。

【风格要求】
{style_anchors}

【世界状态】（当前故事进行到哪里）
{world_state}

【场景目标】
{goal}

【写作要求】
- 严格模仿上述风格样例：白话文言相间的叙事腔调、工笔白描、含蓄的以景衬情
- 人物说话要符合其身份口吻（宝玉痴语、黛玉机敏、凤姐泼辣）
- 用"话说""这日""只见"等章回体过渡语
- 不要写现代词汇，不要直白陈述心理，用动作/景物/对话暗示
- 字数 400-700 字，输出正文即可，不要标题不要解释

正文：
"""


def build_scene_prompt(
    goal: str,
    state: WorldState,
    anchors: list[StyleAnchor],
) -> str:
    return SCENE_PROMPT.replace("{style_anchors}", format_anchors(anchors)).replace(
        "{world_state}", state.describe()
    ).replace("{goal}", goal)


def generate_scene(
    client: LLMClient,
    goal: str,
    state: WorldState,
    anchors: list[StyleAnchor],
) -> str:
    """生成一个场景段落（带一次失败重试），清洗输出残留标记。"""
    prompt = build_scene_prompt(goal, state, anchors)
    for attempt in range(2):
        try:
            raw = client.chat(
                [{"role": "system", "content": prompt}],
                temperature=0.7,
                max_tokens=1000,
            )
            return _clean_output(raw)
        except Exception as e:  # noqa: BLE001
            if attempt == 0:
                continue
            raise RuntimeError(f"文风生成失败: {e}") from e
    return ""
