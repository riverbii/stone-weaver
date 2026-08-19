"""文风引擎 · LLM 文风裁判。

原理：文风是"品味判断"——手工规则（文言虚词/四字格/拟声词）只能测表面
统计，测不了"白描用得好不好""对话是否鲜活"。LLM 能理解语义层面。

设计：
  1. 给裁判看曹雪芹前80回的**风格样本**（文言骈俪段 + 白描段 + 对话段）
  2. 让它对**待测文本**打分（0-10）：文风接近度 + 具体理由 + 修改建议
  3. 输出结构化 JSON，可多次采样取均值（降随机性）
"""

from __future__ import annotations

import json
import re

from ..llm import LLMClient
from ..models import Chapter
from .assess import _clean

JUDGE_PROMPT = """你是一位深谙《红楼梦》文风的资深编辑。下面是曹雪芹原著的风格样本，覆盖三种笔法：

【文言骈俪（大场面/仙境/抒情）】
{wenyan}

【白描叙事（日常场景/动作细节）】
{baomiao}

【人物对话（口语/身份口吻）】
{dialogue}

现在请评价下面这段文本的"文风质量"——它作为《红楼梦》续书的文风如何？

待评文本：
{target}

请只输出一个 JSON 对象：
{{"score": 0-10的整数, "verdict": "好/中/差", "strengths": ["优点1"], "weaknesses": ["缺点1"], "suggestion": "一句改进建议"}}

**重要：只评"文笔文风"，完全不评"内容"**。以下一律不纳入评分：
- 情节、故事走向、人物设定、逻辑、世界观——不评
- 谁做了什么、谁死了、是否违背原著设定——不评
- 诗词韵文的"内容含义"——不评（只评其格律、用词、韵致）

只从"文笔语言"层面评：
- 遣词：典雅度、有无生造词/现代俚俗词（如"搞七捻三""眼乌珠荡"）
- 句式：文言与白话的调度、白描的细节与节奏（"咕咚一跤"式动感 vs "脚酸腿沉"式空泛）
- 对话：口语是否自然生动、有无韵味（不评"这话该不该由某角色说"）
- 韵文：格律是否工整、遣词是否有古意（vs 打油诗/堆砌冷僻字）

评分标准（纯文笔）：
- 9-10：文笔几乎乱真，遣词/白描/对话/文言调度与曹雪芹一致
- 7-8：文笔良好，偶有小疵
- 5-6：文笔一般，有明显的白话现代痕迹或生硬处
- 3-4：文笔明显偏离，白描空泛、对话无味、文言堆砌
- 0-2：完全不像，现代白话或流水账

只输出 JSON，不要其他文字。
"""


def _sample_anchors(db, kind: str, n: int = 2, max_len: int = 300) -> list[str]:
    """从曹雪芹前80回抽风格样本段。"""
    from ..style.anchors import extract_anchors

    anchors = extract_anchors(db, chapters=list(range(1, 41)), per_kind=n)
    out = []
    for a in anchors:
        if a.kind == kind and len(a.text) < max_len:
            out.append(a.text)
    return out


def _split_by_style(db) -> dict[str, str]:
    """抽三类风格样本（文言/白描/对话）。"""
    from ..style.anchors import extract_anchors

    anchors = extract_anchors(db, chapters=list(range(1, 41)), per_kind=2)
    wenyan, baomiao, dialogue = [], [], []
    for a in anchors:
        if a.kind in ("dialogue_jiaoyu", "dialogue_daiyu", "dialogue_fengjie"):
            dialogue.append(a.text)
        elif a.kind in ("scene_landscape", "opening"):
            wenyan.append(a.text)
        elif a.kind in ("action_scene", "scene_emotion"):
            baomiao.append(a.text)
    return {
        "wenyan": "\n".join(wenyan[:2])[:900],
        "baomiao": "\n".join(baomiao[:2])[:900],
        "dialogue": "\n".join(dialogue[:2])[:900],
    }


def judge_style(
    client: LLMClient,
    db,
    target_text: str,
    *,
    samples: int = 1,
) -> dict:
    """LLM 文风裁判。返回 {score, verdict, strengths, weaknesses, suggestion}。

    samples>1 时多次采样取均值（降随机性）。
    """
    anchors = _split_by_style(db)
    prompt = (
        JUDGE_PROMPT.replace("{wenyan}", anchors["wenyan"])
        .replace("{baomiao}", anchors["baomiao"])
        .replace("{dialogue}", anchors["dialogue"])
        .replace("{target}", target_text[:3000])
    )

    results = []
    for _ in range(samples):
        raw = client.chat(
            [{"role": "system", "content": prompt}], temperature=0.3
        )
        s = raw.strip()
        a, b = s.find("{"), s.rfind("}")
        if a == -1 or b <= a:
            continue
        try:
            data = json.loads(s[a : b + 1])
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("score"), (int, float)):
            results.append(data)

    if not results:
        return {"score": None, "verdict": "评估失败", "weaknesses": ["LLM 未返回有效 JSON"]}

    avg = sum(r["score"] for r in results) / len(results)
    best = max(results, key=lambda r: r["score"])
    return {
        "score": round(avg, 1),
        "verdict": best.get("verdict", "中"),
        "strengths": best.get("strengths", []),
        "weaknesses": best.get("weaknesses", []),
        "suggestion": best.get("suggestion", ""),
        "n_samples": len(results),
    }
