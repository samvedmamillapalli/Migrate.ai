import { Link } from "@tanstack/react-router";
import {
  LayoutGrid,
  PlusCircle,
  Zap,
  Clock,
  Brain,
  Settings,
  ChevronLeft,
  Database,
} from "lucide-react";

const linkBase =
  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-all duration-150 group relative";

function NavLink({
  to,
  icon: Icon,
  label,
  badge,
}: {
  to: string;
  icon: typeof Zap;
  label: string;
  badge?: string;
}) {
  return (
    <Link
      to={to}
      className={linkBase + " text-secondary-foreground hover:bg-muted hover:text-foreground"}
      activeProps={{ className: linkBase + " bg-muted text-primary" }}
      activeOptions={{ exact: to === "/" }}
    >
      {({ isActive }) => (
        <>
          <Icon
            className={"h-[18px] w-[18px] shrink-0 " + (isActive ? "text-primary" : "text-muted-foreground")}
            strokeWidth={1.75}
          />
          <span className="flex-1 truncate">{label}</span>
          {badge ? (
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground">
              {badge}
            </span>
          ) : null}
        </>
      )}
    </Link>
  );
}

export function AppSidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-border bg-sidebar md:flex">
      <div className="flex items-start gap-2.5 px-4 pt-5 pb-4">
        <div className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-md bg-primary/10">
          <Database className="h-3.5 w-3.5 text-primary" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <div className="text-[15px] font-bold leading-tight tracking-tight text-foreground">
            Migration Oracle
          </div>
          <div className="text-xs text-muted-foreground">Workspace</div>
        </div>
        <button
          type="button"
          aria-label="Collapse sidebar"
          className="mt-1 text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        <NavLink to="/" icon={LayoutGrid} label="Overview" />

        <div className="section-label px-3 pt-4 pb-1.5">Migrations</div>
        <NavLink to="/new-migration" icon={PlusCircle} label="New Migration" />
        <NavLink to="/current-migration" icon={Zap} label="Current Migration" badge="1" />
        <NavLink to="/past-migrations" icon={Clock} label="Past Migrations" />

        <div className="section-label px-3 pt-4 pb-1.5">Intelligence</div>
        <NavLink to="/agent-memory" icon={Brain} label="Agent Memory" badge="36" />
      </nav>

      <div className="px-3 pb-3">
        <div className="section-label px-3 pb-2">Owner Identity</div>
        <div className="rounded-lg bg-muted px-3 py-2.5">
          <div className="text-sm font-semibold text-foreground">Samved Mamillapalli</div>
          <div className="truncate text-xs text-muted-foreground">samvedmamillapalli@g…</div>
        </div>
      </div>

      <div className="border-t border-border px-3 py-3">
        <Link
          to="/settings"
          activeProps={{ className: "bg-muted text-foreground" }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Settings className="h-[18px] w-[18px] text-muted-foreground" strokeWidth={1.75} />
          Settings
        </Link>
      </div>
    </aside>
  );
}
