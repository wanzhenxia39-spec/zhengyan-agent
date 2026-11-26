import { STATUS_LABEL } from "../format";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge st-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function LevelBadge({ level }: { level: string }) {
  return <span className={`badge lv-${level}`} title={LEVEL_TIP[level]}>{level}</span>;
}

const LEVEL_TIP: Record<string, string> = {
  A: "A 级：结构化财报/行情/公告/系统计算，可支撑结论",
  B: "B 级：权威网页且有快照，只说明发生了什么",
  C: "C 级：线索，只能触发补证，不支撑结论",
};
