"use client"

import * as React from "react"

/**
 * Playful loading captions, in the spirit of Claude Code's "fidgeting…".
 *
 * These replace captions that used to leak internals at the user — the
 * prediction bar, for instance, printed
 * "Calling AWS Bedrock for prediction (us.anthropic.claude-haiku-4-5-…)".
 * The real status still comes from the headline label and the percentage; this
 * is only the flavour line underneath, so it never has to carry information.
 *
 * Deliberately verbs-in-progress and gently silly: enough personality to make a
 * wait feel alive, not so much that it reads as unserious next to a migration
 * risk score.
 */
export const LOADING_WORDS: readonly string[] = [
  "Fidgeting",
  "Tinkering",
  "Pondering",
  "Ruminating",
  "Percolating",
  "Noodling",
  "Deliberating",
  "Puzzling",
  "Mulling",
  "Conjuring",
  "Untangling",
  "Rummaging",
  "Cogitating",
  "Marinating",
  "Whirring",
  "Wrangling",
  "Contemplating",
  "Finagling",
  "Simmering",
  "Scheming",
  "Tessellating",
  "Bamboozling",
  "Reticulating",
  "Hobnobbing",
  "Vibrating",
  "Perusing",
  "Meandering",
  "Kerfuffling",
]

/** How long each word stays on screen. */
const ROTATE_MS = 2600

/**
 * A loading word that changes every few seconds while `active` is true.
 *
 * Starts from a random word so two spinners on one screen do not chant in
 * unison, and stops its timer the moment loading ends.
 */
export function useLoadingWord(active: boolean = true): string {
  const [index, setIndex] = React.useState(() =>
    Math.floor(Math.random() * LOADING_WORDS.length)
  )

  React.useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => {
      // Step by a random non-zero amount so it never cycles in a predictable
      // loop and never repeats the same word twice in a row.
      setIndex(
        (i) =>
          (i + 1 + Math.floor(Math.random() * (LOADING_WORDS.length - 1))) %
          LOADING_WORDS.length
      )
    }, ROTATE_MS)
    return () => window.clearInterval(id)
  }, [active])

  return LOADING_WORDS[index] ?? LOADING_WORDS[0]!
}
