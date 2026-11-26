import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Sparkle } from "../components/Icons";

/** 登录后回到原来要去的页面；只接受站内路径。 */
function nextPath() {
  const n = new URLSearchParams(location.search).get("next") ?? "";
  return n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/login") ? n : "/workspace";
}

export default function Login() {
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await api.login(user.trim(), password); location.assign(nextPath()); }
    catch (err) { setError((err as Error).message); setBusy(false); }
  };

  return (
    <div className="login-page">
      <div className="orb orb-purple" /><div className="orb orb-gold" /><div className="orb orb-pink" />
      <form className="login-card" onSubmit={submit}>
        <Link to="/" className="sb-logo login-logo"><Sparkle className="sb-mark" />证研</Link>
        <h1>登录后进入研究台</h1>
        <p className="muted small">首页可以随便看；研究台、档案和 RSI 等功能需要先登录。</p>
        <label>账号<input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoFocus /></label>
        <label>密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="error" style={{ margin: 0 }}>{error}</div>}
        <button className="primary" type="submit" disabled={busy || !user.trim() || !password}>{busy ? "登录中…" : "登录"}</button>
        <Link to="/" className="muted small login-back">← 返回首页</Link>
      </form>
    </div>
  );
}
