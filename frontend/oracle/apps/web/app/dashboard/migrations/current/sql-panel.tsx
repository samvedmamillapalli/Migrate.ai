import * as React from "react"

import { cn } from "@workspace/ui/lib/utils"

const SQL_KEYWORDS = new Set([
  "ALTER",
  "TABLE",
  "ADD",
  "COLUMN",
  "CONSTRAINT",
  "FOREIGN",
  "KEY",
  "REFERENCES",
  "CREATE",
  "INDEX",
  "CONCURRENTLY",
  "ON",
  "AND",
  "OR",
  "NOT",
  "NULL",
  "PRIMARY",
  "UNIQUE",
  "DROP",
  "SET",
  "DEFAULT",
  "USING",
  "WHERE",
  "SELECT",
  "FROM",
  "INTO",
  "VALUES",
  "UPDATE",
  "DELETE",
  "INSERT",
  "WITH",
])

const SQL_TYPES = new Set([
  "UUID",
  "TEXT",
  "VARCHAR",
  "INTEGER",
  "BIGINT",
  "BOOLEAN",
  "TIMESTAMP",
  "TIMESTAMPTZ",
  "JSONB",
  "NUMERIC",
])

type SqlTokenKind = "keyword" | "type" | "ident" | "number" | "comment" | "plain"

const SQL_TOKEN_CLASS: Record<SqlTokenKind, string> = {
  keyword: "text-[#569CD6]",
  type: "text-[#4EC9B0]",
  ident: "text-[#9CDCFE]",
  number: "text-[#B5CEA8]",
  comment: "text-[#6A9955]",
  plain: "text-[#D4D4D4]",
}

function highlightSqlLine(line: string): React.ReactNode {
  if (line.trimStart().startsWith("--")) {
    return <span className={SQL_TOKEN_CLASS.comment}>{line}</span>
  }
  if (line.length === 0) return "\u00A0"

  const parts = line.split(/(\s+|[{}(),;.]|::)/g)

  return parts.map((part, i) => {
    if (
      !part ||
      /^\s+$/.test(part) ||
      /^[{}(),;.]$/.test(part) ||
      part === "::"
    ) {
      return (
        <span key={i} className={SQL_TOKEN_CLASS.plain}>
          {part}
        </span>
      )
    }

    const upper = part.toUpperCase()
    let kind: SqlTokenKind = "plain"

    if (SQL_KEYWORDS.has(upper)) kind = "keyword"
    else if (SQL_TYPES.has(upper)) kind = "type"
    else if (/^\d+(\.\d+)?$/.test(part)) kind = "number"
    else if (/^'.*'$/.test(part) || /^".*"$/.test(part)) kind = "number"
    else if (/^[a-zA-Z_][\w$]*$/.test(part)) kind = "ident"

    return (
      <span key={i} className={SQL_TOKEN_CLASS[kind]}>
        {part}
      </span>
    )
  })
}

export function SqlCodePanel({
  filename,
  sql,
  className,
}: {
  filename: string
  sql: string
  className?: string
}) {
  const lines = sql.replace(/\r\n/g, "\n").split("\n")

  return (
    <div
      className={cn(
        "overflow-hidden rounded-md border border-[#2D2D2D] bg-[#1E1E1E]",
        className
      )}
    >
      <div className="flex items-center gap-2 border-b border-[#2D2D2D] px-3 py-2">
        <div className="flex items-center gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-[#3C3C3C]" />
          <span className="size-2.5 rounded-full bg-[#3C3C3C]" />
          <span className="size-2.5 rounded-full bg-[#3C3C3C]" />
        </div>
        <span className="truncate font-mono text-[11px] tracking-tight text-[#9D9D9D]">
          {filename}
        </span>
      </div>
      <div className="overflow-x-auto">
        <pre className="p-0 font-mono text-[12px] leading-6">
          <code>
            {lines.map((line, index) => (
              <div key={index} className="flex min-w-full">
                <span className="w-10 shrink-0 select-none pr-3 text-right text-[#858585]">
                  {index + 1}
                </span>
                <span className="pr-4 whitespace-pre">
                  {highlightSqlLine(line)}
                </span>
              </div>
            ))}
          </code>
        </pre>
      </div>
    </div>
  )
}
