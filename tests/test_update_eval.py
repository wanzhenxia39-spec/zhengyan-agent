"""「持续更新」评测：受影响结论有交代、用上新数据、修正有新证据、未受影响结论不无故丢失、可选人工金标。"""
from advisor.evals.update import score_case


def _claim(cid, text, ev=(), status="verified"):
    return {"id": cid, "text": text, "evidence_ids": list(ev), "status": status}


OLD = {"version": 1, "as_of": "2026-10-16", "claims": [
    _claim("c1", "上半年营业收入同比增长百分之五十"),
    _claim("c2", "经营现金流为归母净利润的一点四倍"),
    _claim("c3", "近期公告包括回购进展与董事会决议"),
    _claim("c4", "公司在行业中份额保持第一位置"),
]}
NEW = {"version": 2, "as_of": "2026-11-01",
       "claims": [_claim("n1", "前三季度营业收入同比增长", ["e_q3"]), _claim("n2", "收盘价较前期下跌", ["e_px"]),
                  _claim("n3", "公司在行业中份额保持第一位置")],
       "prior_review": [
           {"prior_claim": "上半年营业收入同比增长百分之五十", "verdict": "retained", "reason": "半年数据不变", "evidence_ids": []},
           {"prior_claim": "经营现金流为归母净利润的一点四倍", "verdict": "weakened", "reason": "三季度下降", "evidence_ids": ["e_q3"]},
       ]}
EVIDENCE = {
    "e_q3": {"id": "e_q3", "source_type": "filing", "as_of": "2026-11-01", "metrics": [{"period": "2026-09-30"}]},
    "e_px": {"id": "e_px", "source_type": "market", "as_of": "2026-10-30", "metrics": []},
}
ALERT = {"id": "A-1", "ticker": "300750", "name": "甲", "events": [
    {"kind": "new_report", "title": "2026-09-30 报告期财报已披露"}, {"kind": "price_move", "title": "价格较档案时点变化 -15.9%"},
    {"kind": "announcement", "title": "档案时点后新增 7 条公告"}],
    "affected": [{"claim_id": "c1"}, {"claim_id": "c2"}]}


def test_update_eval_scores_structure():
    r = score_case(ALERT, OLD, NEW, EVIDENCE)
    m = r["metrics"]
    assert m["coverage"] == 1.0 and m["decisive"] == 1.0          # 受影响的 c1、c2 都有明确判定
    assert m["absorbed"] == 1.0                                   # 新报告期与价格变化都被已核验结论引用
    assert m["grounded"] == 1.0                                   # 削弱的 c2 引用了旧时点之后的证据
    assert m["stable"] == 0.5                                     # c4 仍在；c3 既没复核也没保留
    lost = [c["id"] for c in r["claims"] if not c["affected"] and not c["verdict"] and not c["kept"]]
    assert lost == ["c3"] and m["label_acc"] is None


def test_update_eval_flags_unabsorbed_report_and_uses_labels():
    new = NEW | {"claims": [_claim("n2", "收盘价较前期下跌", ["e_px"])]}
    r = score_case(ALERT, OLD, new, EVIDENCE, {"A-1": {"c1": "retained", "c2": "invalidated"}})
    assert r["absorbed"][0] == {"event": "2026-09-30 报告期财报已披露", "ok": False}
    assert r["metrics"]["label_acc"] == 0.5
