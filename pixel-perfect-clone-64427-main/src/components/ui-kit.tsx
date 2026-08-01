import { motion } from "motion/react";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-foreground">
          {title}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      </div>
      {action}
    </div>
  );
}

export function Panel({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay, ease: [0.22, 1, 0.36, 1] }}
      className={"rounded-xl border border-border bg-card " + className}
    >
      {children}
    </motion.section>
  );
}

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={"section-label " + className}>{children}</div>;
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    "AWAITING APPROVAL": "text-amber-600 bg-amber-50 border-amber-200",
    COMPLETED: "text-emerald-600 bg-emerald-50 border-emerald-200",
    PROCEEDED: "text-emerald-600 bg-emerald-50 border-emerald-200",
    CANCELLED: "text-red-600 bg-red-50 border-red-200",
    PENDING: "text-muted-foreground bg-muted border-border",
    "RUNNING SHADOW": "text-blue-600 bg-blue-50 border-blue-200",
  };
  const dot: Record<string, string> = {
    "AWAITING APPROVAL": "bg-amber-500",
    COMPLETED: "bg-emerald-500",
    PROCEEDED: "bg-emerald-500",
    CANCELLED: "bg-red-500",
    PENDING: "bg-stone-400",
    "RUNNING SHADOW": "bg-blue-500",
  };
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold tracking-wide " +
        (map[status] ?? map['PENDING'])
      }
    >
      <span className={"h-1.5 w-1.5 rounded-full " + (dot[status] ?? dot['PENDING'])} />
      {status}
    </span>
  );
}

export function SqlBlock({ children, className = "" }: { children: string; className?: string }) {
  return (
    <pre
      className={
        "overflow-x-auto whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-foreground " +
        className
      }
    >
      {children}
    </pre>
  );
}
