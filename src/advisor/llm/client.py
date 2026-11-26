"""DeepSeek（OpenAI 兼容接口）。代码按角色取模型，输出必须通过 Pydantic Schema。"""
import json
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from advisor.settings import Settings, load_yaml


class LLMOutputError(Exception):
    pass


class LLMNotConfigured(RuntimeError):
    """没有配置大模型 Key：服务可以启动、浏览已有数据，但不能发起新研究。"""


class DeepSeekClient:
    def __init__(self, settings: Settings, roles: dict[str, Any] | None = None):
        self.roles = roles or load_yaml("models.yaml", settings.config_dir)["roles"]
        # 没配 Key 也允许服务启动（可以浏览已有档案、RSI 账本和评测结果）；真正调用模型时才报错
        self._client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=300,
            max_retries=2,
        ) if settings.deepseek_api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def json(self, role: str, system: str, user: str, schema: type[BaseModel]) -> tuple[BaseModel, int]:
        if self._client is None:
            raise LLMNotConfigured("未配置 DEEPSEEK_API_KEY：请在 .env 中填写后重启服务")
        cfg = self.roles[role]
        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": f"{system}\n\n只输出一个 JSON 对象，符合以下 JSON Schema：\n{schema_hint}"},
            {"role": "user", "content": user},
        ]
        tokens = 0
        for attempt in range(2):  # 一次修复重试
            resp = self._client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                response_format={"type": "json_object"},
                extra_body={"reasoning_effort": cfg.get("effort", "high")},
            )
            tokens += resp.usage.total_tokens if resp.usage else 0
            content = resp.choices[0].message.content or ""
            try:
                return schema.model_validate_json(content), tokens
            except ValidationError as e:
                if attempt == 1:
                    raise LLMOutputError(f"模型输出不符合 Schema: {e.errors()[:2]}") from e
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"上面的 JSON 不符合 Schema：{e.errors()[:3]}。请修正后只输出 JSON。"},
                ]
        raise LLMOutputError("unreachable")
