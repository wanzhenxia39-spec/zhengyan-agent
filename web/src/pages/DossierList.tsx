import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { fmtTime } from "../format";

type Row = Awaited<ReturnType<typeof api.dossiers>>[number];

export default function DossierList() {
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => { api.dossiers().then(setRows); }, []);
  return (
    <div className="page">
      <h1>决策档案</h1>
      <p className="muted">每个标的一份档案，每次研究生成新版本，旧版本保留。</p>
      {rows === null ? <p className="muted">加载中…</p> : rows.length === 0 ? (
        <p className="muted">还没有档案。<Link to="/new">新建研究</Link></p>
      ) : (
        <div className="grid">
          {rows.map((d) => (
            <Link key={d.key} to={`/dossiers/${d.key}/${d.version}`} className="card dossier-card">
              <div className="title-row">
                <b>{d.name}</b><code>{d.ticker}</code><span className="tag">v{d.version}</span>
                <StatusBadge status={d.status} />
              </div>
              <p className="clamp">{d.summary}</p>
              <div className="muted small">数据截至 {d.as_of} · 更新于 {fmtTime(d.created_at)}</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
