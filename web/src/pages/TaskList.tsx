import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { fmtTime } from "../format";
import type { Task } from "../types";

export default function TaskList() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  useEffect(() => { api.tasks().then(setTasks); }, []);
  return (
    <div className="page narrow">
      <h1>任务</h1>
      {tasks === null ? <p className="muted">加载中…</p> : tasks.length === 0 ? (
        <p className="muted">还没有任务。<Link to="/new">新建研究</Link></p>
      ) : (
        <div className="list">
          {tasks.map((t) => (
            <Link key={t.task_id} to={`/tasks/${t.task_id}`} className="list-item">
              <StatusBadge status={t.status} />
              <span className="grow">{t.request.question}</span>
              <span className="muted small">{fmtTime(t.created_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
