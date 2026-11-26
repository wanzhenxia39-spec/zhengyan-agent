import type { Alert, PersonalFit, ProfileState, ProfileVersion, StrategyCard, StrategyEvent, StrategyOverview, StrategySpec, NavPoint, PaperTrade, Subscription, Holding, RiskProfile, AuditRecord, Dossier, DossierDiff, EvalRun, Evidence, Meta, RsiAsset, RsiEvent, RsiIssue, RsiJob, RsiOverview, RsiRun, Task, WatchRow, WorkingItem, ProfileImpact } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (res.status === 401 && path !== "/api/login") toLogin();
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  }
  return res.json();
}

/** 未登录：跳到登录页，登录后回到当前页面。 */
export function toLogin() {
  if (location.pathname === "/" || location.pathname === "/login") return;
  location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
}

export const api = {
  session: () => req<{ required: boolean; logged_in: boolean }>("/api/session"),
  login: (user: string, password: string) =>
    req<{ ok: boolean }>("/api/login", { method: "POST", body: JSON.stringify({ user, password }) }),
  logout: () => req<{ ok: boolean }>("/api/logout", { method: "POST" }),
  research: (body: { question: string; ticker?: string; as_of?: string; route: string }) =>
    req<{ task_id: string }>("/api/research", { method: "POST", body: JSON.stringify(body) }),
  task: (id: string) => req<Task>(`/api/tasks/${id}`),
  tasks: () => req<Task[]>("/api/tasks"),
  resume: (id: string, approve: boolean) =>
    req<{ ok: boolean }>(`/api/tasks/${id}/resume`, { method: "POST", body: JSON.stringify({ approve }) }),
  audit: (id: string) => req<AuditRecord[]>(`/api/tasks/${id}/audit`),
  cancel: (id: string) => req<{ status: string }>(`/api/tasks/${id}/cancel`, { method: "POST" }),
  workspace: (id: string) => req<WorkingItem[]>(`/api/tasks/${id}/workspace`),
  meta: () => req<Meta>("/api/meta"),
  diff: (key: string, version: number) => req<DossierDiff>(`/api/dossiers/${key}/${version}/diff`),
  evals: () => req<EvalRun[]>("/api/evals"),
  evalRun: (id: string) => req<EvalRun>(`/api/evals/${id}`),
  startUpdateEval: () => req<{ run_id: string }>("/api/evals/update", { method: "POST" }),
  startRoutingEval: () => req<{ submitted: boolean }>("/api/evals/routing", { method: "POST" }),
  startCompare: (body: { case_ids?: string[]; routes: string[] }) =>
    req<{ run_id: string }>("/api/evals/compare", { method: "POST", body: JSON.stringify(body) }),
  dossiers: () => req<(Pick<Dossier, "key" | "ticker" | "name" | "version" | "status" | "as_of" | "summary" | "created_at">)[]>("/api/dossiers"),
  versions: (key: string) => req<Pick<Dossier, "key" | "version" | "status" | "as_of" | "question" | "created_at">[]>(`/api/dossiers/${key}/versions`),
  dossier: (key: string, version: number) => req<{ dossier: Dossier; evidence: Evidence[] }>(`/api/dossiers/${key}/${version}`),
  watchlist: () => req<WatchRow[]>("/api/watchlist"),
  rsi: {
    overview: () => req<RsiOverview>("/api/rsi/overview"),
    issues: (scenario?: string) => req<RsiIssue[]>(`/api/rsi/issues${scenario ? `?scenario=${scenario}` : ""}`),
    runs: () => req<RsiRun[]>("/api/rsi/runs"),
    run: (id: string) => req<{ run: RsiRun; base: RsiAsset | null; issues: RsiIssue[]; events: RsiEvent[]; job: RsiJob | null }>(`/api/rsi/runs/${id}`),
    events: () => req<RsiEvent[]>("/api/rsi/events"),
    collect: () => req<Record<string, number>>("/api/rsi/collect", { method: "POST" }),
    propose: (scenario: string, issue_id?: string) =>
      req<{ job_id: string }>("/api/rsi/propose", { method: "POST", body: JSON.stringify({ scenario, issue_id }) }),
    evaluate: (id: string) => req<{ job_id: string }>(`/api/rsi/runs/${id}/evaluate`, { method: "POST" }),
    approve: (id: string, note: string) => req<RsiRun>(`/api/rsi/runs/${id}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
    reject: (id: string, reason: string) => req<RsiRun>(`/api/rsi/runs/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
    release: (id: string) => req<RsiRun>(`/api/rsi/runs/${id}/release`, { method: "POST" }),
    rollback: (kind: string, reason: string) =>
      req<{ kind: string; from: number; to: number }>("/api/rsi/rollback", { method: "POST", body: JSON.stringify({ kind, reason }) }),
    job: (id: string) => req<RsiJob>(`/api/rsi/jobs/${id}`),
  },
  job: (id: string) => req<RsiJob>(`/api/jobs/${id}`),
  profile: {
    get: () => req<ProfileState>("/api/profile"),
    confirm: (body: { risk: RiskProfile; holdings: Holding[]; change_note: string; confirmed: boolean }) =>
      req<ProfileVersion>("/api/profile", { method: "POST", body: JSON.stringify(body) }),
    fit: (ticker: string) => req<{ fit: PersonalFit; holding: Holding | null;
      profile_change: (ProfileImpact & { profile_version: number; confirmed_at: string }) | null }>(`/api/profile/fit/${ticker}`),
  },
  watch: {
    overview: () => req<{ subscriptions: Subscription[]; alerts: Alert[]; interval_hours: number }>("/api/watch"),
    subscribe: (ticker: string, price_move_pct?: number) =>
      req<Subscription>("/api/watch/subscriptions", { method: "POST", body: JSON.stringify({ ticker, price_move_pct }) }),
    unsubscribe: (ticker: string) => req<{ ok: boolean }>(`/api/watch/subscriptions/${ticker}`, { method: "DELETE" }),
    scanAll: () => req<{ job_id: string }>("/api/watch/scan", { method: "POST" }),
    scan: (ticker: string) => req<{ alert: Alert | null }>(`/api/watch/scan/${ticker}`, { method: "POST" }),
    review: (id: string) => req<{ task_id: string }>(`/api/watch/alerts/${id}/review`, { method: "POST" }),
    dismiss: (id: string, note: string) => req<{ ok: boolean }>(`/api/watch/alerts/${id}/dismiss`, { method: "POST", body: JSON.stringify({ note }) }),
  },
  strategy: {
    overview: () => req<StrategyOverview>("/api/strategy"),
    create: (body: StrategySpec & { change_reason: string; card_id?: string }) =>
      req<StrategyCard>("/api/strategy", { method: "POST", body: JSON.stringify(body) }),
    detail: (id: string, v: number) =>
      req<{ card: StrategyCard; navs: NavPoint[]; trades: PaperTrade[]; versions: { version: number; status: string; change_reason: string }[]; events: StrategyEvent[] }>(`/api/strategy/${id}/${v}`),
    paper: (id: string, v: number) => req<StrategyCard>(`/api/strategy/${id}/${v}/paper`, { method: "POST" }),
    step: () => req<{ job_id: string }>("/api/strategy/step", { method: "POST" }),
    submit: (id: string, v: number) => req<StrategyCard>(`/api/strategy/${id}/${v}/submit`, { method: "POST" }),
    approve: (id: string, v: number, note: string) => req<StrategyCard>(`/api/strategy/${id}/${v}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
    reject: (id: string, v: number, reason: string) => req<StrategyCard>(`/api/strategy/${id}/${v}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
    rollback: (id: string, reason: string) => req<StrategyCard>(`/api/strategy/${id}/rollback`, { method: "POST", body: JSON.stringify({ reason }) }),
  },
  snapshot: async (id: string) => {
    const res = await fetch(`/api/evidence/${id}/snapshot`);
    if (res.status === 401) toLogin();
    return res.ok ? res.text() : "";
  },
};

/** 轮询后台作业（RSI 提议/评测、订阅扫描、模拟盘推进）直到结束。 */
export async function waitJob(id: string, onLog?: (j: RsiJob) => void): Promise<RsiJob> {
  for (;;) {
    const j = await api.job(id);
    onLog?.(j);
    if (j.status !== "running") return j;
    await new Promise((r) => setTimeout(r, 1500));
  }
}
