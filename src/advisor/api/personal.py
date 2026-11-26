"""三期：用户确认档案与个人情境官。写入只有一条路径：用户在界面上明确确认。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from advisor.api.common import OWNER, Svc, conflict_on
from advisor.personal import ProfileError, ProfileInput, assess

router = APIRouter(prefix="/api/profile")


class ConfirmIn(ProfileInput):
    confirmed: bool = False       # 界面上的「我确认以上信息由我本人填写」


@router.get("")
def profile(svc: Svc):
    cur = svc.profiles.current()
    return {"current": cur.model_dump(mode="json") if cur else None,
            "history": [v.model_dump(mode="json") for v in svc.profiles.history()]}


@router.post("")
def confirm(body: ConfirmIn, svc: Svc):
    with conflict_on(ProfileError):
        v = svc.confirm_profile(ProfileInput.model_validate(body.model_dump()), OWNER, body.confirmed)
    return v.model_dump(mode="json")


class FitOut(BaseModel):
    fit: dict
    holding: dict | None
    profile_change: dict | None = None    # 最近一次修改约束让这份档案的个人情境结论变了


@router.get("/fit/{ticker}", response_model=FitOut)
def fit(ticker: str, svc: Svc):
    """个人情境官：把最新档案对照你确认过的约束。纯本地规则，不调用模型。"""
    d = svc.deps.repo.get_dossier(ticker)
    if d is None:
        raise HTTPException(404, "档案不存在")
    profile = svc.profiles.current()
    sub = svc.watch.store.get_sub(ticker)
    alerts = [(a.id, "、".join(e.title for e in a.events)) for a in svc.watch.store.list_alerts(ticker, "open")]
    result = assess(d, svc.deps.repo.get_evidence(d.evidence_ids), profile, bool(sub and sub.active), alerts)
    holding = profile.holding(ticker) if profile else None
    change = next((x for x in (profile.impact if profile else []) if x["ticker"] == ticker), None)
    return {"fit": result.model_dump(mode="json"), "holding": holding.model_dump(mode="json") if holding else None,
            "profile_change": change and {**change, "profile_version": profile.version,
                                          "confirmed_at": profile.confirmed_at.isoformat()}}
