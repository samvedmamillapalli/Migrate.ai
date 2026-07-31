import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronUp, X } from "lucide-react";

export function ShadowWatch() {
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-4 right-4 z-40 w-[320px] rounded-xl border border-border bg-foreground px-4 py-3 text-background shadow-lg"
        >
          <div className="flex items-start gap-2.5">
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
            <div className="flex-1">
              <div className="text-[11px] font-bold uppercase tracking-[0.08em]">Shadow Watch</div>
              <div className="mt-0.5 text-[13px] font-medium text-background/90">
                Finished — expand for results
              </div>
              <AnimatePresence initial={false}>
                {expanded ? (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="mt-2 space-y-1 font-mono text-[11px] text-background/70">
                      <div>replica-03 · 1m 47s</div>
                      <div>0 deadlocks · no lock escalation</div>
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
            <button
              type="button"
              aria-label="Expand shadow watch"
              onClick={() => setExpanded((v) => !v)}
              className="text-background/60 transition-colors hover:text-background"
            >
              <ChevronUp className={"h-4 w-4 transition-transform " + (expanded ? "rotate-180" : "")} />
            </button>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => setOpen(false)}
              className="text-background/60 transition-colors hover:text-background"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
