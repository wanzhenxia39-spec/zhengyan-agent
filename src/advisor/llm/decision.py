"""本地决策小模型（System One 接口：Kev 本地服务或 TypeSafe Jev 云端，二者接口相同）。

只做"选一个标签"：给一段文本和若干单选题，返回每题的概率分布。不生成文字，结果不进入结论或证据。
"""
from typing import Any

import httpx


class DecisionError(Exception):
    pass


class DecisionClient:
    def __init__(self, base_url: str, model: str = "kev-latest", api_key: str = "local", timeout_s: float = 3.0):
        self.model = model
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s,
                                    headers={"Authorization": f"Bearer {api_key}"})

    def choose(self, state: str, questions: dict[str, tuple[str, dict[str, str]]]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        """questions: {问题 id: (说明, {选项: 选项描述})} → ({问题 id: {选项: 概率}}, 元信息)。"""
        body = {"model": self.model, "state": state,
                "questions": {qid: {"type": "choice", "instructions": instr, "criteria": crit}
                              for qid, (instr, crit) in questions.items()}}
        try:
            r = self._client.post("/v1/systemone", json=body)
            r.raise_for_status()
            data = r.json()
            answers = {qid: {k: float(v) for k, v in data["answers"][qid]["probabilities"].items()} for qid in questions}
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            raise DecisionError(f"决策模型不可用：{str(e)[:120]}") from e
        meta = {"model": data.get("model", self.model), "latency_ms": data.get("latency_ms")}
        return answers, meta
