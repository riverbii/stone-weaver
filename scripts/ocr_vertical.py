#!/usr/bin/env python3
"""古籍竖排 OCR：按列切分 → 旋转 → RapidOCR 识别 → 从右到左拼接。

用法: .venv/bin/python scripts/ocr_vertical.py <图片路径>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_COL_DENSITY = 60  # 一列最少暗像素数才算文字列
MIN_COL_WIDTH = 30  # 一列最小宽度


def detect_columns(img_gray: np.ndarray, page_w: int) -> list[tuple[int, int]]:
    """检测竖排列边界。返回 [(x_start, x_end)] 从右到左。"""
    col_density = (img_gray < 128).sum(axis=0)
    # 找连续的"文字区"（密度>阈值）
    regions: list[list[int]] = []
    cur: list[int] = []
    for x in range(page_w):
        if col_density[x] > MIN_COL_DENSITY:
            cur.append(x)
        else:
            if cur:
                regions.append(cur)
                cur = []
    if cur:
        regions.append(cur)
    # 合并相邻近的区域（同一列可能有微小空白）
    merged: list[tuple[int, int]] = []
    for r in regions:
        x0, x1 = r[0], r[-1]
        if merged and x0 - merged[-1][1] < 12:
            prev = merged.pop()
            merged.append((prev[0], x1))
        else:
            merged.append((x0, x1))
    # 过滤太窄的（可能是装饰）
    merged = [(a, b) for a, b in merged if b - a >= MIN_COL_WIDTH]
    # 从右到左排序（古籍从右往左读）
    merged.sort(key=lambda x: -x[0])
    return merged


def ocr_column(ocr, col_img: Image.Image, x0: int, x1: int) -> str:
    """识别一列（竖排列 → 旋转成横排）。"""
    # 列是竖排的（文字从上到下），旋转 -90 度变横排（字正立）
    # 但竖排古籍阅读顺序是从上到下、从右到左，旋转后列内文字应能横排识别
    rot = col_img.rotate(-90, expand=True)
    tmp = "/tmp/ocr_col.png"
    rot.save(tmp)
    result, _ = ocr(tmp)
    if not result:
        return ""
    # 旋转后：列内从上到下 → 横排从左到右；按 x 排序
    texts = sorted(result, key=lambda x: x[0][0][0])
    return "".join(item[1] for item in texts)


def main() -> int:
    path = sys.argv[1]
    img = Image.open(path).convert("L")
    W, H = img.size
    gray = np.array(img)

    cols = detect_columns(gray, W)
    print(f"检测到 {len(cols)} 列", [f"{a}-{b}" for a, b in cols])

    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()

    # 每列加边距提取
    pad = 6
    full_text = []
    for x0, x1 in cols:
        cx0, cx1 = max(0, x0 - pad), min(W, x1 + pad)
        col_img = img.crop((cx0, 0, cx1, H))
        text = ocr_column(ocr, col_img, x0, x1)
        full_text.append(text)
        print(f"  列[{x0}-{x1}]: {text[:40]}")

    print("\n===== 拼接结果 =====")
    print("".join(full_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
