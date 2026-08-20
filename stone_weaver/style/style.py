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
7. **"话说"最多用 1 次**（只在本场景开头起新线时用；正文中间严禁再用"话说/且说/却说"另起炉灶）。段落开头要多样自然：可用"只见""一进门""说笑之间""忽见""正说着""一时""谁知"等承接前文，不要每段都从人名重新起头
8. **"X听了"句式严禁流水线**：全场景"听了"最多 2 次；"X听了"后不能总是接"道"——可以接转述（"宝玉听了这话，公然又是一个袭人"）、接内心判断（"王夫人听了这话内有因"）、接比喻（"如雷轰电掣一般"）、接动作去向（"晴雯听了，只得拿了帕子往潇湘馆来"）
9. **句式变化**：不要连续三句用"X道："开头；对话引导词轮换（笑道/叹道/忙道/啐道/悄声道/正色道）；叙述句不要都从人名开始
10. **禁情感套路词（本段内一律不用）**：半晌、怔了、眼圈、哽咽、喉头、心头一紧、说不出话、好半晌、半晌方、愣住、眼眶湿润、怔怔地——这些是小说腔拖延词，曹雪芹几乎不用。情绪用动作与对话表现（"把茶盅往桌上一顿""啐了一口""低头拭泪"），禁止"半晌不语"式静态标签
11. 字数 300-500 字，输出正文即可

正文：
"""


def build_scene_prompt(
    goal: str,
    state: WorldState,
    anchors: list[StyleAnchor],
    prev_tail: str = "",
    feedback: str = "",
) -> str:
    prompt = SCENE_PROMPT.replace("{style_anchors}", format_anchors(anchors)).replace(
        "{world_state}", state.describe()
    ).replace("{goal}", goal)
    if prev_tail:
        prompt = prompt.replace(
            "正文：",
            f"【前文结尾（请自然衔接，不要用\"话说\"另起，直接从场景衔接处续写）】\n……{prev_tail}\n\n正文：",
        )
    if feedback:
        prompt = prompt.replace("正文：", f"{feedback}\n\n正文：")
    return prompt


def generate_scene(
    client: LLMClient,
    goal: str,
    state: WorldState,
    anchors: list[StyleAnchor],
    prev_tail: str = "",
    feedback: str = "",
) -> str:
    """生成一个场景段落（带一次失败重试），清洗输出残留标记。"""
    prompt = build_scene_prompt(goal, state, anchors, prev_tail, feedback)
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
