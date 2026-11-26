export type Level = "A" | "B" | "C";

export interface Metric {
  name: string; field: string; value: string; unit: string; period: string; basis: string; note: string;
}

export interface Evidence {
  id: string; level: Level; source_type: string; title: string; source_url: string | null;
  site_name: string | null; origin_publisher: string | null; cluster_id: string | null;
  published_at: string | null; as_of: string; pit: "strong" | "weak"; excerpt: string;
  metrics: Metric[]; derived_from: string[]; authority: number | null; rerank_score: number | null;
  caveats: string[]; skill: string; skill_version: string;
}

export interface Claim {
  id: string; text: string; kind: "fact" | "inference" | "assumption" | "scenario";
  evidence_ids: string[]; status: "candidate" | "verified" | "disputed" | "rejected" | "stale"; verify_notes: string[];
}

export interface Dossier {
  key: string; version: number; parent_version: number | null; ticker: string; name: string; as_of: string;
  question: string; route: string; status: "committed" | "partial"; summary: string; claims: Claim[];
  unknowns: string[]; dissents: { text: string; evidence_ids: string[] }[];
  review_triggers: { condition: string; reason: string }[]; evidence_ids: string[];
  quality: { decision: string; verified: number; disputed: number; rejected: number; gaps: string[]; notes: string[] };
  boundary_notes: string[]; task_id: string; created_at: string; report_md: string;
  routing: RouteDecision | null; deliberation: Deliberation | null; prior_review: PriorReview[]; clue_ids: string[];
  rsi_versions?: Versions; lessons_used?: string[];
}

export interface RouteDecision {
  route: "quick" | "standard" | "deep"; source: string; probs: Record<string, number>;
  calibrated: Record<string, number>; stakes: string | null; uncertainty: string | null; abstain: boolean;
  reasons: string[]; escalated_from: string | null;
}

export interface ExpertResult {
  expert: string; name: string; model_role: string; brief: string[]; queries: string[]; own_evidence_ids: string[];
  seen_evidence: number; claims: Claim[]; stance: string; confidence: string; open_questions: string[];
  usage: Record<string, number>; duration_ms: number; error: string | null;
}

export interface Challenge {
  id: string; target_claim_id: string; target_expert: string; kind: string; text: string;
  evidence_ids: string[]; severity: "low" | "mid" | "high"; evidence_ok: boolean; notes: string[];
}
export interface ResponseItem { challenge_id: string; expert: string; stance: "concede" | "rebut" | "revise"; text: string; evidence_ids: string[]; revised_claim: Claim | null }
export interface Ruling { challenge_id: string; verdict: "upheld" | "rejected" | "unresolved"; reason: string; severity: string }

export interface Deliberation {
  mode: "map_reduce" | "debate" | "committee"; rationale: string; team: ExpertResult[]; challenges: Challenge[];
  responses: ResponseItem[]; rulings: Ruling[]; committee: { expert: string; position: string }[];
  adopted_claim_ids: string[]; needs_human_review: boolean;
}

export interface PriorReview { prior_claim: string; verdict: "retained" | "weakened" | "invalidated" | "unverifiable"; reason: string; evidence_ids: string[] }

export interface DossierDiff {
  from_version: number; to_version: number; as_of: { old: string; new: string }; route: { old: string; new: string };
  status: { old: string; new: string };
  metrics: { name: string; old: MetricSnap | null; new: MetricSnap | null; changed: boolean }[];
  claims: { kept: { old: string; new: string; similarity: number }[]; added: string[]; removed: string[] };
  stale_claims: { text: string; reason: string }[];
  evidence_added: { id: string; title: string; level: Level; source_type: string; date: string | null }[];
  unknowns: { resolved: string[]; new: string[] }; triggers: { old: string[]; new: string[] }; prior_review: PriorReview[];
}
export interface MetricSnap { value: string; unit: string; period: string; basis: string }

export interface WorkingItem { task_id: string; kind: string; key: string; data: any; created_at: string }

export interface EvalMetrics {
  claims: number; verified: number; disputed: number; rejected: number; verified_rate: number; numeric_claims: number;
  numeric_accuracy: number; coverage: Record<string, boolean>; coverage_rate: number; dissents: number; unknowns: number;
  independent_b_sources: number; quality_decision: string; tokens: number; search_calls: number; fetch_calls: number;
  seconds: number; score: number;
}
/** 「持续更新」评测的一个案例：一次订阅提醒 → 重新研究。 */
export interface UpdateCase {
  alert_id: string; ticker: string; name: string; from_version: number; to_version: number; old_as_of: string; new_as_of: string;
  events: string[]; metrics: Record<string, number | null>; absorbed: { event: string; ok: boolean }[];
  claims: { id: string; text: string; affected: boolean; verdict: string | null; reason: string; kept: boolean }[];
}
export interface EvalRun {
  run_id: string; type: "compare" | "routing" | "update"; status: string; created_at: string;
  routes?: string[]; cases?: { id: string; question: string }[]; case_count?: number;
  results?: { case: string; route: string; task_id?: string; dossier_key?: string; version?: number; metrics?: EvalMetrics; error?: string }[];
  update_results?: UpdateCase[]; metric_labels?: Record<string, string>; update_summary?: Record<string, number | null>; labeled?: number;
  summary?: { routes: Record<string, Record<string, number>>; verdict: { decision: string; text: string; quality_delta?: number; cost_ratio?: number; non_inferior?: boolean; affordable?: boolean; criteria?: Record<string, number> } };
  rows?: { question: string; label: string; route: string; source: string; probs: Record<string, number>; abstain: boolean; correct: boolean }[];
  confusion?: Record<string, Record<string, number>>; accuracy?: number; deep_recall?: number; abstain_rate?: number;
  calibration?: { by_temperature: Record<string, { nll: number; ece: number; abstain_rate: number }>; best_temperature: number };
  current?: { temperature: number; abstain_below: number };
}

export interface Meta {
  experts: { key: string; name: string; mandate: string; constraint: string; role: string }[];
  routes: Record<string, { llm_role: string; budget: Record<string, number> }>;
  routing: Record<string, any>; expert_cfg: Record<string, number>;
}

export interface TaskEvent { ts: string; node: string; message: string }

export interface Task {
  task_id: string; status: "queued" | "running" | "waiting_approval" | "done" | "failed" | "cancelled";
  request: { question: string; ticker: string | null; as_of: string | null; route: string };
  events?: TaskEvent[]; interrupt: { type: string; message: string; items?: string[]; skill?: string; version?: string; ttl_s?: number } | null;
  result: { dossier_key: string; version: number; route?: string; routing?: RouteDecision;
    budget?: { limits: Record<string, number>; used: Record<string, number> } } | null;
  error: string | null; created_at: string;
}

export interface AuditRecord {
  ts: string; kind: "skill" | "llm"; name: string; status: string; duration_ms: number; node?: string; principal?: string;
  version?: string; role?: string; tokens?: number; error?: string; trace_id?: string; span_id?: string;
}

// ---------- 研究台 / RSI ----------
export type RsiKind = "lessons" | "routing" | "search";
export type Versions = Partial<Record<RsiKind, number | null>>;

export interface WatchRow {
  key: string; ticker: string; name: string; version: number; status: string; as_of: string; summary: string;
  created_at: string; route: string | null; rsi_versions: Versions;
  quote: Partial<Record<"close" | "chg_20d" | "pe_ttm" | "pe_pct", { value: string; unit: string; period: string }>>;
  subscribed: boolean; open_alerts: number;
}

export interface LessonCard {
  id: string; title: string; applies_to: string; tags: string[]; lesson: string; must_check: string[];
  invalid_if: string; source: string; rev: number;
}
export interface RsiIssue {
  id: string; scenario: "S1" | "S2" | "S3"; kind: string; case: string; evidence: string[]; hypothesis: string;
  source: Record<string, any>; status: "open" | "addressed" | "dropped"; created_at: string;
}
export interface GateResult { name: string; label: string; passed: boolean; detail: string }
export interface SliceStat { runs: number[]; mean: number | null; spread: number | null }
export interface RsiArm { slices: Record<string, SliceStat>; tokens: number; cards?: string[]; note?: string; params?: Record<string, number>; deep_recall?: SliceStat }
export interface RsiEval {
  scenario: string; repeats: number; primary: string; metric: string; deterministic?: boolean;
  arms: Record<"base" | "cand" | "off", RsiArm>;
  protocol: { scorer: string; hash: string; replay_hash: string; slices: Record<string, { n: number; bad?: number }> };
  leakage: { evolution: string[]; holdout: string[] };
  samples?: Record<string, { id: string; label: string; text: string; dossier: string }[]>;
}
export interface RsiRun {
  run_id: string; scenario: "S1" | "S2" | "S3"; kind: RsiKind; issue_ids: string[]; base_version: number;
  content?: Record<string, any>; diff: { action?: string; cards?: LessonCard[]; params?: Record<string, [number, number]>;
    hint?: { expert: string; name: string; old: string; new: string; rationale?: string }; sites?: { add?: string[]; remove?: string[] } };
  change_reason: string; direction: string; risk?: "normal" | "high";
  status: "draft" | "review" | "approved" | "released" | "archived" | "rejected" | "rolled_back";
  proposer: string; triggered_by: string; eval: RsiEval | null; has_eval?: boolean; gates: GateResult[];
  approvals: { by: string; note: string; self_approved: boolean }[]; released_version: number | null;
  reject_reason: string | null; created_at: string; updated_at: string;
}
export interface RsiEvent { action: string; actor: string; ts: string; detail?: string; run_id?: string; kind?: string; self_approved?: boolean }
export interface RsiAsset { kind: RsiKind; version: number; parent_version: number | null; content: Record<string, any>; sha256: string; change_reason: string; run_id: string | null; created_by: string; created_at: string }
export interface RsiOverview {
  loop: Record<"collect" | "propose" | "evaluate" | "gates" | "release", { done: boolean; count: number; rollback?: number }>;
  active: Record<RsiKind, { label: string; version: number; sha256: string; change_reason: string; created_at: string; content: Record<string, any> } | null>;
  lineage: Record<RsiKind, { version: number; parent: number | null; sha256: string; run_id: string | null; change_reason: string; created_at: string; active: boolean }[]>;
  counterfactual: { run_id: string; metric: string; arms: Record<string, { slices: Record<string, SliceStat>; tokens: number; cards?: string[]; note?: string }> } | null;
  issues: Record<"S1" | "S2" | "S3", { open: number; total: number }>;
  inheritance: { versions: Versions; dossiers: number; lessons_used: string[]; last: string }[];
  self_approved: number;
}
export interface RsiJob { job_id: string; kind: string; status: "running" | "done" | "failed"; log: string[]; result: string | null; error: string | null }

// ---------- 三期：用户确认档案、个人情境官、订阅与增量复核 ----------
export interface RiskProfile { max_drawdown_pct: number | null; horizon_months: number | null; liquidity_note: string }
export interface Holding { ticker: string; name: string; thesis: string; horizon_months: number | null }
export interface ProfileVersion {
  version: number; parent_version: number | null; risk: RiskProfile; holdings: Holding[]; change_note: string;
  confirmed_by: string; confirmed_at: string; impact?: ProfileImpact[];
}
/** 修改约束后，某份档案的个人情境结论哪里变了（系统计算）。 */
export interface ProfileImpact {
  ticker: string; name: string; dossier_version: number; before: string; after: string;
  changes: { key: string; label: string; before: FitStatus; after: FitStatus; detail: string }[];
}
export interface ProfileState { current: ProfileVersion | null; history: ProfileVersion[] }
export type FitStatus = "ok" | "attention" | "conflict" | "unknown";
export interface FitCheck { key: string; label: string; status: FitStatus; detail: string; refs: string[] }
export interface PersonalFit {
  ticker: string; dossier_version: number; profile_version: number | null; checks: FitCheck[]; summary: string; disclaimer: string;
}
export interface Subscription { ticker: string; name: string; price_move_pct: number; active: boolean; created_at: string; last_scan_at: string | null; last_scan_note: string }
export interface WatchEvent { kind: "new_report" | "announcement" | "price_move" | "trigger"; title: string; detail: string; date: string | null; evidence_ids: string[] }
export interface Alert {
  id: string; ticker: string; name: string; dossier_key: string; dossier_version: number; events: WatchEvent[];
  affected: { claim_id: string; text: string; reason: string }[]; status: "open" | "reviewing" | "resolved" | "dismissed";
  created_at: string; review_task_id: string | null; resolved_version: number | null; note: string;
}

// ---------- 四期：策略卡与前向模拟盘 ----------
export interface Rule { field: string; op: "<" | "<=" | ">" | ">=" | "==" | "!="; value: number | string }
export interface StrategySpec {
  name: string; thesis: string; universe: string[]; entry: Rule[]; exit: Rule[]; max_positions: number;
  stop_loss_pct: number | null; max_drawdown_limit: number;
}
export interface StrategyCard extends StrategySpec {
  card_id: string; version: number; parent_version: number | null;
  status: "draft" | "paper" | "review" | "promoted" | "rejected" | "retired" | "rolled_back";
  change_reason: string; sha256: string; created_by: string; created_at: string; paper_start: string | null;
  gates: GateResult[]; approvals: { actor: string; note: string; self_approved: boolean; at: string }[]; reject_reason: string;
  stats: { days: number; return_pct: number; max_drawdown_pct: number };
}
export interface NavPoint { date: string; nav: number; cash: number; positions: { ticker: string; shares: number; cost: number; price: number; opened: string }[]; notes: string[] }
export interface PaperTrade { date: string; ticker: string; side: "open" | "close"; shares: number; price: number; reason: string; dossier_version: number | null; evidence_ids: string[] }
export interface StrategyEvent { ts: string; action: string; actor: string; card_id: string; version: number; detail: string; self_approved?: boolean }
export interface StrategyOverview {
  cards: StrategyCard[]; fields: Record<string, string>; status_label: Record<string, string>; initial_cash: number;
  gates_cfg: Record<string, number>; events: StrategyEvent[];
}
