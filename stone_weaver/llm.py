from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 项目根 data/.env（gitignore 内）：STONE_LLM_BASE_URL / STONE_LLM_API_KEY / STONE_LLM_MODEL
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / "data" / ".env")

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


class LLMClient:
    """OpenAI 兼容 chat completions 客户端。

    配置（环境变量）：
      STONE_LLM_BASE_URL  默认 https://opencode.ai/zen/go/v1
      STONE_LLM_API_KEY   必填
      STONE_LLM_MODEL     默认 deepseek-v4-flash
    """

    def __init__(
        self,
        *,
        max_retries: int = 4,
        retry_base: float = 6.0,
    ) -> None:
        self.base_url = os.getenv("STONE_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.api_key = os.getenv("STONE_LLM_API_KEY", "")
        self.model = os.getenv("STONE_LLM_MODEL", DEFAULT_MODEL)
        self.max_retries = max_retries
        self.retry_base = retry_base
        if not self.api_key:
            raise RuntimeError("STONE_LLM_API_KEY 未设置，请在 data/.env 中配置")

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=120,
                )
                # 429 限流 / 5xx 网关不稳 → 指数退避重试
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = self.retry_base * (2 ** (attempt - 1))
                    print(
                        f"[llm] HTTP {resp.status_code}，{wait:.0f}s 后重试 ({attempt}/{self.max_retries})",
                        flush=True,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait = self.retry_base * (2 ** (attempt - 1))
                    print(
                        f"[llm] HTTP {e.response.status_code}，{wait:.0f}s 后重试 ({attempt}/{self.max_retries})",
                        flush=True,
                    )
                    time.sleep(wait)
                    last_err = e
                    continue
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < self.max_retries:
                    wait = self.retry_base * (2 ** (attempt - 1))
                    print(
                        f"[llm] 网络错误 {type(e).__name__}，{wait:.0f}s 后重试 ({attempt}/{self.max_retries})",
                        flush=True,
                    )
                    time.sleep(wait)
                    last_err = e
                    continue
                raise
        raise RuntimeError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_err}")
