"""Skill 契约：类型、权限、版本、输入输出 Schema、超时。"""
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict


class SkillSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    version: str
    category: Literal["data", "compute", "research", "action"]
    permission: Literal["read", "write", "approval"]
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    timeout_s: float = 60
    egress_fields: tuple[str, ...] = ()   # 会发到外部服务的自由文本字段，出域前检查敏感信息
    budget_kind: Literal["search_calls", "fetch_calls"] | None = None
    retryable: tuple[type[Exception], ...] = ()


class Skill(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: SkillSpec
    run: Callable[[Any], BaseModel]
