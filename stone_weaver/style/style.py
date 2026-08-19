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

【写作要求——曹雪芹叙事法，务必逐条遵守】
1. **用动作和对话推进，不抒情、不描写风景凑数**：写"谁做了什么、说了什么、谁又做了什么"，不要写"唯余…仿佛…罢了"这类景物抒情收尾
2. **句子短而实**：多用 10-25 字的动作/对话句，少用 40 字以上的长句；一句一个动作，不堆砌修饰
3. **人物互动密集**：让两个以上人物对话、抢话、动作交锋，不要单人独白太长
4. **对话符合人物**：宝玉痴语（"女儿是水做的骨肉"式）、黛玉机敏带刺、凤姐泼辣市井、婆子们粗鄙直白
5. **白描**：动作直写（"起身""摔帘子""啐了一口"），不解释心理，情感藏于动作对话
6. **禁止**：被字句（"被…照着/被…拉住"）、"仿佛/似乎/如同/不过…罢了/唯有/唯余"等现代抒情词、景物结尾
7. 不要堆砌"话说/这日/只见"过渡词（每段最多 1 次）
8. 字数 300-500 字，输出正文即可

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
