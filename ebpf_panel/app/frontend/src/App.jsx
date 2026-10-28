import { Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Shield, FileText,
  MessageSquare, Activity, Cpu, ShieldX,
} from 'lucide-react'
import DashboardPage from './pages/DashboardPage'
import DetectionsPage from './pages/DetectionsPage'
import ReportsPage from './pages/ReportsPage'
import ChatPage from './pages/ChatPage'
import ServicesPage from './pages/ServicesPage'
import BansPage from './pages/BansPage'

const links = [
  { to: '/',           label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/detections', label: 'Détections',  icon: Shield },
  { to: '/bans',       label: 'IPs bannies', icon: ShieldX },
  { to: '/reports',    label: 'Rapports',    icon: FileText },
  { to: '/chat',       label: 'Chat IA',     icon: MessageSquare },
  { to: '/services',   label: 'Services',    icon: Activity },
]

export default function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        {/* Brand */}
        <div className="brand">
          <div className="brand-icon">
            <Cpu />
          </div>
          <div>
            <div className="brand-name">eBPF Panel</div>
            <div className="brand-sub">IA · Security</div>
          </div>
        </div>

        {/* Nav */}
        <nav className="nav">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
            >
              <Icon />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="sidebar-footer">v0.1.0 · Local</div>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/"           element={<DashboardPage />} />
          <Route path="/detections" element={<DetectionsPage />} />
          <Route path="/reports"    element={<ReportsPage />} />
          <Route path="/chat"     element={<ChatPage />} />
          <Route path="/bans"     element={<BansPage />} />
          <Route path="/services" element={<ServicesPage />} />
        </Routes>
      </main>
    </div>
  )
}
