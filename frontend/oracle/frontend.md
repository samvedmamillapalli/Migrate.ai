# Migration Oracle — Frontend Design System

Last updated: July 2026

---

# ## Before generating UI Always understand the backend models and existing terminology before creating frontend components. Do not invent new concepts if equivalent ones already exist in the backend. Use the language already present in the repository whenever possible.

# Philosophy

Migration Oracle is an infrastructure product for developers.

The interface should communicate confidence, clarity, and precision rather than creativity.

Users should feel like they are operating production infrastructure, not interacting with an AI product or a marketing website.

The interface should be calm, restrained, and intentionally minimal.

When deciding between adding another visual element or removing one, prefer removing it.

---

# Design References

The product should feel at home beside:

- Vercel
- GitHub
- CockroachDB Cloud
- Railway
- Resend

These are references for quality and interaction patterns, not templates to copy.

---



# Principles

1. Typography is more important than decoration.
2. Whitespace is more valuable than borders.
3. Every component should have a clear purpose.
4. Motion should support understanding, never exist for decoration.
5. Avoid visual noise.

---



# Visual Language



## Theme

Dark only.

Background

#0A0A0A

Surfaces should use slightly lighter shades of gray.

Never use pure black.

---



## Corners

Default

rounded-xl

Interactive pills

rounded-full

Never mix many different border radii.

---



## Borders

Use borders sparingly.

Border color should always be subtle.

Prefer one meaningful border over several nested borders.

---



## Shadows

Minimal.

Most components should have no visible shadow.

Large floating shadows are prohibited.

---



## Glass

Do not use glassmorphism.

No frosted cards.

No blurred floating panels.

---



## Gradients

Do not use gradients for:

- backgrounds
- cards
- buttons
- hero sections
- typography

Gradients may only appear inside illustrations if ever needed.

---



# Colors

Primary UI

Neutral grayscale.

Accent colors should communicate meaning.

Green

Success

Amber

Warning

Red

Failure

Blue should not become the dominant visual identity.

---



# Typography

Font

Geist Sans

Code

Geist Mono



---



## Headings

Large.

Bold.

Short.

Readable.

Avoid wrapping onto many lines.

---



## Body

Readable.

Comfortable line spacing.

Muted foreground.

---



## Labels

Small.

Uppercase only where appropriate.

Avoid unnecessary badges.

---



# Icons

Lucide only.

Icons should support text, not replace it.

Never decorate empty space with icons.

---



# Layout

Maximum width

max-w-7xl

Content width

max-w-3xl

Section spacing

120px vertical

Hero spacing

160px top padding

Generous horizontal padding.

---



# Navigation

Height

72px

Structure

Left

- Logo
- Migration Oracle

Center

- Docs
- GitHub

Right

- Sign In
- Get Started

---



## Behaviour

Sticky.

Transparent while at the top.

Apply backdrop blur once the page scrolls.

Add a subtle bottom border after scrolling.

---



## Navigation Links

Default

Muted text.

Hover

- rounded-full
- muted background
- foreground text
- transition around 200ms

Active

Slightly brighter background.

Medium font weight.

Never underline links.

---



# Buttons



## Primary

Filled.

High contrast.

Rounded-full.

Used only for primary actions.

Hover

Slight brightness increase.

Very small scale increase if any.

No glow.

No bounce.

---



## Secondary

Ghost or outline.

Used for supporting actions.

---



# Hero

Headline first.

Everything else supports it.

Maximum headline length

14 words.

Subtitle

One concise paragraph.

Maximum width

Approximately 700px.

CTA buttons directly underneath.

The product preview sits below the hero copy.

---



# Product Preview

The preview represents the real application.

It is not an illustration.

It should evolve alongside the actual application.

Structure

Left

Icon rail

↓

Runs list

↓

SQL editor

↓

Shadow Analysis

One outer container.

One vertical divider.

No floating cards.

No nested dashboards.

---



# Motion

Motion should be subtle.

Preferred

- fade
- opacity
- translateY
- blur reveal
- text reveal

Avoid

- bouncing
- spinning
- elastic effects
- large parallax
- floating objects

Animations should complete in approximately 200–300ms.

---



# Components

Always prefer shadcn/ui.

Custom components should follow the same visual language.

Never introduce a component that visually belongs to another design system.

---



# Code

TypeScript.

Functional React components.

Small reusable components.

Avoid duplicated layouts.

Prefer composition.

Use Tailwind.

Avoid inline styles.

---



# Things We Never Add

Analytics charts on the landing page.

Gradient hero backgrounds.

Glassmorphism.

Random floating blobs.

Animated counters.

Fake notifications.

Stock illustrations.

AI sparkles.

Neon effects.

Overly decorative icons.

Marketing buzzwords.

---



# Goal

Every page should feel like it belongs to the same product.

A user should be able to move from the landing page into the application without feeling that they have entered a different website.

---



# Operating System Primitives

Migration Oracle is an operating system for database migrations.

Canonical imports:

`@/components/system`

`@/lib/oracle-tokens`

## Semantic colors

| Token | Meaning | Use |
| --- | --- | --- |
| Gray (`structure`) | Structure | Borders, tracks, idle nodes, chrome |
| White (`content`) | Content | Titles, values, readable copy |
| Purple (`reasoning`) | Active reasoning | Current AI / analysis stage only |
| Green (`verified`) | Verified | Successful completion only |
| Red (`risk`) | Rollback risk | Warnings and failures only |

Do not use decorative colors. Do not theme the whole UI purple.

## Spacing

Scale: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64.

Section rhythm: 120px.

Hero top: 160px.

## Radii

| Role | Token |
| --- | --- |
| Nodes / controls | `rounded-md` |
| Status surfaces | `rounded-lg` |
| Panels / windows | `rounded-xl` |
| Pills / primary CTAs | `rounded-full` |

## Typography

| Role | Usage |
| --- | --- |
| `display` | Landing headlines |
| `title` | Section titles |
| `subtitle` | One supporting sentence |
| `body` | Dense UI copy |
| `label` | Field labels, meta |
| `mono` / `monoSm` | SQL, metrics, logs |

## Motion

Ease-out: `[0.16, 1, 0.3, 1]`

| Duration | When |
| --- | --- |
| 120ms | Micro feedback |
| 200ms | Crossfades, node opacity |
| 280ms | Default state change |
| 450ms | Connector growth, panel entrance |
| 650ms | Workflow step dwell (orchestration) |

Every animation must represent a real state transition.

## Icon sizes

12 / 14 / 16 / 20 px.

## Primitives

| Component | Job |
| --- | --- |
| `FlowLine` | Structural gray track |
| `AnimatedConnector` | Growing progress between nodes |
| `ThinkingNode` | Active purple reasoning node |
| `ExecutionNode` | Pending / verified / risk node |
| `StatusTransition` | Current operation + status + details |
| `WorkflowTimeline` | Composed step list |
| `PacketAnimation` | Single packet in transit (only while flowing) |
| `PredictionComparison` | Predicted vs actual block |
| `TerminalStream` | Append-only execution log |
| `MetricRow` | One metric comparison row |
| `DeveloperPanel` | One outer app surface |
| `SectionHeader` | Section title + optional sentence |

## Rules

1. Prefer removing a primitive usage over nesting panels.
2. Purple never appears on idle chrome.
3. Green never means “brand” — only verified.
4. `PacketAnimation` must not loop on idle screens.
5. Prefer `StatusTransition` over custom status cards.