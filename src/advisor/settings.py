from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    decision_base_url: str = ""   # 本地决策小模型（Kev）地址；为空则不启用，路由走大模型
    decision_model: str = "kev-latest"
    decision_api_key: str = "local"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "advisor"
    config_dir: Path = ROOT / "config"
    reports_dir: Path = ROOT / "reports"
    auth_user: str = ""          # 访问账号密码：设置了密码才启用（对外分享链接时用）
    auth_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or get_settings().config_dir) / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
