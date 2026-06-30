import { NavLink, Outlet } from "react-router-dom";
import { BackendStatus } from "./BackendStatus";

/**
 * The underwriter-facing application shell — a left sidebar (desktop) / top nav (mobile) + content.
 * Clean, spacious, flag-accented. Used by the console, the consortium simulator, and the master model.
 */
const NAV = [
  { to: "/console", label: "Underwriter console", icon: "▣", sub: "Verify & decide" },
  { to: "/consortium", label: "Consortium", icon: "◍", sub: "Multi-bank network" },
  { to: "/model", label: "Master model", icon: "✦", sub: "Federated rules" },
];

export function AppShell() {
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      {/* Sidebar (md+) */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-hairline bg-surface md:flex">
        <div className="flag-rule h-1 w-full" aria-hidden />
        <NavLink to="/onboarding" className="flex items-center gap-3 px-5 py-5">
          <span className="gradient-accent flex h-10 w-10 items-center justify-center rounded-xl text-lg text-white shadow-card">
            सत्
          </span>
          <div>
            <p className="font-semibold text-navy">Satyum</p>
            <p className="text-[11px] text-slate-500">Canara Bank</p>
          </div>
        </NavLink>
        <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition " +
                (isActive ? "bg-navy-soft font-semibold text-navy" : "text-slate-400 hover:bg-surface-2")
              }
            >
              <span aria-hidden className="text-base">
                {n.icon}
              </span>
              <span className="flex flex-col">
                <span>{n.label}</span>
                <span className="text-[11px] font-normal text-slate-500">{n.sub}</span>
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="px-3 pb-2">
          <BackendStatus />
        </div>
        <NavLink to="/onboarding" className="m-3 mt-0 rounded-xl border border-hairline px-3 py-2.5 text-center text-sm font-medium text-slate-300 hover:bg-surface-2">
          + New application
        </NavLink>
      </aside>

      {/* Top nav (mobile) */}
      <header className="border-b border-hairline bg-surface md:hidden">
        <div className="flag-rule h-1 w-full" aria-hidden />
        <div className="flex items-center gap-2 overflow-x-auto px-4 py-3">
          <span className="mr-2 font-semibold text-navy">Satyum</span>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm " +
                (isActive ? "gradient-accent text-white" : "text-slate-400")
              }
            >
              {n.label}
            </NavLink>
          ))}
        </div>
      </header>

      <main className="flex-1 px-5 py-8 sm:px-8">
        <div className="mx-auto w-full max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
