"""计算类 Skill：同口径同比、单季推算、比率。完全确定性。"""
from pydantic import BaseModel

from advisor.contracts import Metric
from advisor.contracts.skill import Skill, SkillSpec
from advisor.skills.compute.finance import ratio, same_basis_growth, single_quarter


class GrowthIn(BaseModel):
    current: Metric
    prior: Metric


class SingleQuarterIn(BaseModel):
    cumulative: Metric
    previous_cumulative: Metric | None = None


class RatioIn(BaseModel):
    numerator: Metric
    denominator: Metric
    name: str
    field: str


class MetricOut(BaseModel):
    metric: Metric


def build_compute_skills() -> list[Skill]:
    common = dict(category="compute", permission="read", output_model=MetricOut, timeout_s=5)
    return [
        Skill(spec=SkillSpec(name="compute.same_basis_growth", version="1.0.0", input_model=GrowthIn,
                             description="同字段、同口径、同报告期的同比增长", **common),
              run=lambda i: MetricOut(metric=same_basis_growth(i.current, i.prior))),
        Skill(spec=SkillSpec(name="compute.single_quarter", version="1.0.0", input_model=SingleQuarterIn,
                             description="由累计值推算单季值", **common),
              run=lambda i: MetricOut(metric=single_quarter(i.cumulative, i.previous_cumulative))),
        Skill(spec=SkillSpec(name="compute.ratio", version="1.0.0", input_model=RatioIn,
                             description="同期同口径比率（%）", **common),
              run=lambda i: MetricOut(metric=ratio(i.numerator, i.denominator, i.name, i.field))),
    ]
