"""全局配置：所有章节共用。

为什么单独抽出这个文件？
因为"模型从哪来"这件事在教程里最容易碎——每章各写一份 client 配置，
换个模型要改十几处。集中到一处后，.env 改一行全书生效。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class Settings(BaseModel):
    """运行期配置。全部来自环境变量，不写死在代码里。"""

    api_key: str = Field(default="missing", alias="OPENAI_API_KEY")
    base_url: str = Field(default="https://api.deepseek.com/v1", alias="OPENAI_BASE_URL")
    model: str = Field(default="deepseek-chat", alias="MODEL_NAME")
    cheap_model: str = Field(default="deepseek-chat", alias="CHEAP_MODEL_NAME")
    trace_dir: Path = Field(default=ROOT / ".traces")

    model_config = {"populate_by_name": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    aliases = {f.alias for f in Settings.model_fields.values() if f.alias}
    return Settings(**{k: v for k, v in os.environ.items() if k in aliases})


def make_llm(model: str | None = None, temperature: float = 0.0, **kwargs):
    """统一的模型工厂。

    通过 OpenAI 兼容协议连任意厂商（DeepSeek / 通义 / Ollama / vLLM ...），
    这样教程不会被某一家绑定。
    """
    from langchain_openai import ChatOpenAI

    s = get_settings()
    return ChatOpenAI(
        model=model or s.model,
        api_key=s.api_key,
        base_url=s.base_url,
        temperature=temperature,
        **kwargs,
    )
