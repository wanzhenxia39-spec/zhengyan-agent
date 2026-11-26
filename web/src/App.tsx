import { Route, Routes, useLocation } from "react-router-dom";
import Shell from "./components/Shell";
import DossierList from "./pages/DossierList";
import DossierView from "./pages/DossierView";
import Evals from "./pages/Evals";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import NewResearch from "./pages/NewResearch";
import Profile from "./pages/Profile";
import Rsi from "./pages/Rsi";
import RsiRun from "./pages/RsiRun";
import Strategy from "./pages/Strategy";
import StrategyCard from "./pages/StrategyCard";
import System from "./pages/System";
import TaskDetail from "./pages/TaskDetail";
import TaskList from "./pages/TaskList";
import Watch from "./pages/Watch";
import Workspace from "./pages/Workspace";

export default function App() {
  const loc = useLocation();
  if (loc.pathname === "/") return <Landing />;
  if (loc.pathname === "/login") return <Login />;
  return (
    <Shell>
      <Routes>
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/new" element={<NewResearch />} />
        <Route path="/tasks" element={<TaskList />} />
        <Route path="/tasks/:id" element={<TaskDetail />} />
        <Route path="/dossiers" element={<DossierList />} />
        <Route path="/dossiers/:key" element={<DossierView />} />
        <Route path="/dossiers/:key/:version" element={<DossierView />} />
        <Route path="/evals" element={<Evals />} />
        <Route path="/evals/:id" element={<Evals />} />
        <Route path="/rsi" element={<Rsi />} />
        <Route path="/rsi/runs/:id" element={<RsiRun />} />
        <Route path="/watch" element={<Watch />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/strategy" element={<Strategy />} />
        <Route path="/strategy/:id/:version" element={<StrategyCard />} />
        <Route path="/system" element={<System />} />
        <Route path="*" element={<Workspace />} />
      </Routes>
    </Shell>
  );
}
