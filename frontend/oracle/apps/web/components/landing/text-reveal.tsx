"use client"

import * as React from "react"
import {
  motion,
  useInView,
  useReducedMotion,
  type Transition,
} from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

export type TextRevealPart = {
  text: string
  italic?: boolean
  className?: string
}

export type TextRevealLine = {
  parts: TextRevealPart[]
}

const EASE_OUT: Transition["ease"] = [0.16, 1, 0.3, 1]

type TextRevealProps = {
  lines: TextRevealLine[]
  className?: string
  lineClassName?: string
  as?: "h1" | "h2" | "p"
  id?: string
  /** Total duration for each line reveal (~0.8s). */
  duration?: number
  /** Delay between successive lines. */
  lineStagger?: number
  onComplete?: () => void
}

/**
 * Line-based Text Reveal — each line fades up once on first viewport entry.
 */
export function TextReveal({
  lines,
  className,
  lineClassName,
  as: Tag = "h1",
  id,
  duration = 0.8,
  lineStagger = 0.12,
  onComplete,
}: TextRevealProps) {
  const ref = React.useRef<HTMLElement | null>(null)
  const inView = useInView(ref, { once: true, amount: 0.4 })
  const prefersReducedMotion = useReducedMotion()
  const completedRef = React.useRef(false)

  React.useEffect(() => {
    if (!inView || completedRef.current || !onComplete) return
    const totalMs =
      (duration + lineStagger * Math.max(0, lines.length - 1)) * 1000 + 40
    const timer = window.setTimeout(() => {
      completedRef.current = true
      onComplete()
    }, prefersReducedMotion ? 0 : totalMs)
    return () => window.clearTimeout(timer)
  }, [inView, onComplete, duration, lineStagger, lines.length, prefersReducedMotion])

  return (
    <Tag
      ref={ref as React.RefObject<HTMLHeadingElement>}
      id={id}
      className={cn(className)}
      aria-label={lines.map((l) => l.parts.map((p) => p.text).join("")).join(" ")}
    >
      {lines.map((line, lineIndex) => (
        <span
          key={lineIndex}
          className={cn("block overflow-hidden", lineClassName)}
          aria-hidden
        >
          <motion.span
            className="block"
            initial={
              prefersReducedMotion
                ? false
                : { opacity: 0, y: "100%" }
            }
            animate={
              inView || prefersReducedMotion
                ? { opacity: 1, y: "0%" }
                : { opacity: 0, y: "100%" }
            }
            transition={{
              duration: prefersReducedMotion ? 0 : duration,
              delay: prefersReducedMotion ? 0 : lineIndex * lineStagger,
              ease: EASE_OUT,
            }}
          >
            {line.parts.map((part, partIndex) =>
              part.italic ? (
                <em
                  key={partIndex}
                  className={cn("font-medium italic", part.className)}
                >
                  {part.text}
                </em>
              ) : (
                <span key={partIndex} className={part.className}>
                  {part.text}
                </span>
              )
            )}
          </motion.span>
        </span>
      ))}
    </Tag>
  )
}
