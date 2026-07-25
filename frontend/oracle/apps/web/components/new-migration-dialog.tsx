"use client"

import * as React from "react"
import { FileCode2, GitBranch, Diff, ClipboardPaste } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@workspace/ui/components/dialog"
import { cn } from "@workspace/ui/lib/utils"

type MigrationInputMethod =
  | "upload"
  | "paste"
  | "repository"
  | "compare"
  | null

const METHODS: {
  id: Exclude<MigrationInputMethod, null>
  title: string
  description: string
  icon: React.ElementType
  comingSoon?: boolean
}[] = [
  {
    id: "upload",
    title: "Upload SQL File",
    description: "Upload a .sql migration file.",
    icon: FileCode2,
  },
  {
    id: "paste",
    title: "Paste SQL",
    description: "Paste migration SQL directly into an editor.",
    icon: ClipboardPaste,
  },
  {
    id: "repository",
    title: "Connect Repository",
    description: "Select a migration from a GitHub repository.",
    icon: GitBranch,
    comingSoon: true,
  },
  {
    id: "compare",
    title: "Compare Schema",
    description: "Generate a migration from schema differences.",
    icon: Diff,
    comingSoon: true,
  },
]

export function NewMigrationDialog() {
  const [open, setOpen] = React.useState(false)
  const [method, setMethod] = React.useState<MigrationInputMethod>(null)
  const [sqlText, setSqlText] = React.useState("")
  const [fileName, setFileName] = React.useState<string | null>(null)
  const [isDragging, setIsDragging] = React.useState(false)
  const fileInputRef = React.useRef<HTMLInputElement>(null)

  function resetState() {
    setMethod(null)
    setSqlText("")
    setFileName(null)
    setIsDragging(false)
  }

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) resetState()
  }

  function acceptSqlFile(file: File | undefined) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith(".sql")) return
    setFileName(file.name)
    void file.text().then(setSqlText)
  }

  function onDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsDragging(false)
    acceptSqlFile(event.dataTransfer.files[0])
  }

  const canRun =
    method === "upload"
      ? Boolean(fileName)
      : method === "paste"
        ? sqlText.trim().length > 0
        : false

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button className="w-full shrink-0 sm:w-auto" />}>
        New Migration
      </DialogTrigger>

      <DialogContent className="sm:max-w-xl" showCloseButton>
        <DialogHeader>
          <DialogTitle>New Migration</DialogTitle>
          <DialogDescription>
            Choose how you want to provide your database migration.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 sm:grid-cols-2">
          {METHODS.map((item) => {
            const selected = method === item.id
            const Icon = item.icon
            return (
              <button
                key={item.id}
                type="button"
                disabled={item.comingSoon}
                onClick={() => setMethod(item.id)}
                className={cn(
                  "border-border hover:bg-muted/40 flex flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors",
                  selected && "border-foreground/30 bg-muted/30",
                  item.comingSoon && "cursor-not-allowed opacity-50"
                )}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Icon className="text-muted-foreground size-3.5" />
                    <span className="text-foreground text-sm font-medium">
                      {item.title}
                    </span>
                  </div>
                  {item.comingSoon ? (
                    <span className="text-muted-foreground font-mono text-[10px] tracking-tight uppercase">
                      Coming soon
                    </span>
                  ) : null}
                </div>
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {item.description}
                </p>
              </button>
            )
          })}
        </div>

        {method === "upload" ? (
          <div className="space-y-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".sql,text/plain"
              className="hidden"
              onChange={(event) => acceptSqlFile(event.target.files?.[0])}
            />
            <div
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  fileInputRef.current?.click()
                }
              }}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              className={cn(
                "border-border flex min-h-28 cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed px-4 py-6 text-center",
                isDragging && "border-foreground/40 bg-muted/20"
              )}
            >
              <p className="text-foreground text-sm">
                Drop a .sql file here, or click to browse
              </p>
              <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
                {fileName ?? "Accepted format: .sql"}
              </p>
            </div>
          </div>
        ) : null}

        {method === "paste" ? (
          <div className="space-y-2">
            <label
              htmlFor="migration-sql"
              className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
            >
              Migration SQL
            </label>
            <textarea
              id="migration-sql"
              value={sqlText}
              onChange={(event) => setSqlText(event.target.value)}
              spellCheck={false}
              placeholder="-- paste migration SQL"
              className={cn(
                "border-input bg-background text-foreground placeholder:text-muted-foreground",
                "focus-visible:border-ring focus-visible:ring-ring/50",
                "min-h-40 w-full resize-y rounded-md border px-3 py-2 font-mono text-[12px] leading-relaxed outline-none",
                "focus-visible:ring-3"
              )}
            />
          </div>
        ) : null}

        {(method === "upload" || method === "paste") && (
          <>
            <div className="border-border/60 grid gap-3 border-t pt-3 sm:grid-cols-2">
              <div className="space-y-0.5">
                <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                  Source
                </p>
                <p className="text-foreground font-mono text-xs tracking-tight">
                  PostgreSQL
                </p>
              </div>
              <div className="space-y-0.5">
                <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                  Target
                </p>
                <p className="text-foreground font-mono text-xs tracking-tight">
                  CockroachDB
                </p>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                disabled={!canRun}
                onClick={() => handleOpenChange(false)}
              >
                Run Migration Analysis
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
