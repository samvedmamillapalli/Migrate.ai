import { ArrowUpRight } from "lucide-react";

export interface JournalEntry {
  date: string;
  readTime: string;
  title: string;
  excerpt: string;
  href: string;
  image: string;
  alt: string;
}

export function JournalCard({ entry }: { entry: JournalEntry }) {
  return (
    <a
      href={entry.href}
      target="_blank"
      rel="noreferrer"
      className="group block rounded-3xl border border-border bg-surface p-5 transition-all hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-28px_rgba(31,27,26,0.45)] sm:p-7"
    >
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_300px] md:items-center">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <span className="text-foreground">{entry.date}</span>
            <span aria-hidden>•</span>
            <span>{entry.readTime}</span>
          </div>
          <h2 className="font-display mt-3 text-[26px] leading-[1.1] tracking-[-0.5px] text-foreground sm:text-[32px]">
            {entry.title}
          </h2>
          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">{entry.excerpt}</p>
          <span className="mt-5 inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-4 py-2 text-[12px] font-semibold text-foreground transition-colors group-hover:border-foreground/30">
            Read on Medium
            <ArrowUpRight className="size-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </span>
        </div>
        <div className="overflow-hidden rounded-2xl">
          <img
            src={entry.image}
            alt={entry.alt}
            loading="lazy"
            className="h-[190px] w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
          />
        </div>
      </div>
    </a>
  );
}