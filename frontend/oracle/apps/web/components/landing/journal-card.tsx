import { ArrowUpRight } from "lucide-react"

export type JournalEntry = {
  date: string
  readTime: string
  title: string
  excerpt: string
  href: string
  image: string
  alt: string
}

export function JournalCard({ entry }: { entry: JournalEntry }) {
  return (
    <a
      href={entry.href}
      target="_blank"
      rel="noreferrer"
      className="border-border bg-surface group block rounded-3xl border p-5 transition-all hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-28px_rgba(31,27,26,0.45)] sm:p-7"
    >
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_300px] md:items-center">
        <div className="min-w-0">
          <div className="text-muted-foreground flex items-center gap-2 text-[13px]">
            <span className="text-foreground">{entry.date}</span>
            <span aria-hidden>•</span>
            <span>{entry.readTime}</span>
          </div>
          <h2 className="font-display text-foreground mt-3 text-[26px] leading-[1.1] tracking-[-0.5px] sm:text-[32px]">
            {entry.title}
          </h2>
          <p className="text-muted-foreground mt-3 text-[13px] leading-relaxed">
            {entry.excerpt}
          </p>
          <span className="border-border bg-background text-foreground group-hover:border-foreground/30 mt-5 inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-[12px] font-semibold transition-colors">
            Read on Medium
            <ArrowUpRight className="size-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </span>
        </div>
        <div className="overflow-hidden rounded-2xl">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={entry.image}
            alt={entry.alt}
            loading="lazy"
            className="h-[190px] w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
          />
        </div>
      </div>
    </a>
  )
}
