"""把配置也声明成模型：默认值、类型、必填项一次写清。

运行：python code/knowledge/ch05_pydantic/settings_demo.py
"""

import os

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="forbid")

    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = Field(min_length=1)
    timeout_s: float = 30.0
    max_retries: int = 2


os.environ["AGENT_API_KEY"] = "sk-demo"
print(Settings())

os.environ["AGENT_TIMEOUT_S"] = "3.5"
os.environ["AGENT_MAX_RETRIES"] = "1"
print(Settings())

os.environ["AGENT_API_KEY"] = ""
try:
    Settings()
except ValidationError as exc:
    print("配置不合法：", exc.errors()[0]["loc"], exc.errors()[0]["msg"])
