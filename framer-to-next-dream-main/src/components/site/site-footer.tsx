export function SiteFooter({
  left = "Migration Oracle / 2026",
  right = "AI-powered database migration",
  bordered = false,
  uppercaseLeft = false,
}: {
  left?: string;
  right?: string;
  bordered?: boolean;
  uppercaseLeft?: boolean;
}) {
  return (
    <footer className="mx-auto w-full max-w-[1180px] px-6 pb-14 pt-10">
      <div
        className={
          bordered
            ? "flex flex-wrap items-center justify-between gap-3 border-t border-border pt-6"
            : "flex flex-wrap items-center justify-between gap-3"
        }
      >
        <span
          className={`text-[12px] font-medium tracking-[0.12em] text-muted-foreground ${
            uppercaseLeft ? "uppercase" : ""
          }`}
        >
          {left}
        </span>
        <span className="text-[13px] text-muted-foreground">{right}</span>
      </div>
    </footer>
  );
}