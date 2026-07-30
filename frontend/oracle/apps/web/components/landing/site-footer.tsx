export function SiteFooter({
  left = "Migration Oracle / 2026",
  right = "AI-powered database migration",
  bordered = false,
  uppercaseLeft = false,
}: {
  left?: string
  right?: string
  bordered?: boolean
  uppercaseLeft?: boolean
}) {
  return (
    <footer className="mx-auto w-full max-w-[1180px] px-6 pt-10 pb-14">
      <div
        className={
          bordered
            ? "border-border flex flex-wrap items-center justify-between gap-3 border-t pt-6"
            : "flex flex-wrap items-center justify-between gap-3"
        }
      >
        <span
          className={`text-muted-foreground text-[12px] font-medium tracking-[0.12em] ${
            uppercaseLeft ? "uppercase" : ""
          }`}
        >
          {left}
        </span>
        <span className="text-muted-foreground text-[13px]">{right}</span>
      </div>
    </footer>
  )
}
