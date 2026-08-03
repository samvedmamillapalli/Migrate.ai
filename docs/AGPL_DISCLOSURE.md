# AGPL source in the corpus — Mattermost

Written 2026-08-03, alongside the open-source corpus expansion documented in
`docs/corpus_info.md`. This is a narrow disclosure about one corpus entry,
not a statement about the project's own license (see the repo root
`LICENSE`, unaffected).

## What's included

One record, `data/open_source_corpus/mattermost_property_field_rank_backfill.json`,
derived from a real migration file in
[mattermost/mattermost](https://github.com/mattermost/mattermost):
`server/channels/db/migrations/postgres/000198_convert_classification_fields_to_rank.up.sql`.

That file lives under Mattermost's core server source, which the repo's own
`LICENSE.txt` places under **AGPLv3** for source use (compiled builds
distributed by Mattermost, Inc. are separately MIT-licensed; a small set of
admin/config directories — `server/templates/`, `server/i18n/`,
`server/public/`, `webapp/` — carry an Apache-2.0 carve-out, but the
migrations directory is not among them). Verified directly against the real
`LICENSE.txt` content on 2026-08-03, not assumed from the doc's prior
research.

## Why this is in scope for a permissive-license corpus

The rest of this corpus is MIT/Apache-2.0/BSD-3-Clause — this is the one
exception, included deliberately after evaluating what AGPLv3 actually
restricts:

- **Use here is read-and-analyze, not redistribution.** One migration file
  was read, summarized, and its DDL pattern (a JSONB-configured field type
  change with an inline backfill) was written up as a memory record. No
  Mattermost source code, compiled binary, or modified version of
  Mattermost is shipped, built, or hosted by this project.
- **This project is not a Mattermost derivative.** Migration Oracle doesn't
  link against Mattermost, embed its code, or present any part of itself as
  a Mattermost-based product. AGPL's copyleft obligations attach to
  distributing or hosting a modified version of the covered work — neither
  applies here.
- **No Mattermost branding appears anywhere in this project.** The
  corpus record cites its source (repo URL, file path) the same way every
  other entry does; nothing is rebranded or presented as Mattermost's own UI.

## Countly — researched, not included

`docs/corpus_info.md` also researched Countly's AGPLv3-plus-branding-terms
license in comparable depth, on the assumption it would be included
alongside Mattermost. It was not: Countly is a MongoDB-only application —
a real search of its repository turned up zero `.sql` files anywhere in the
codebase. There is no SQL migration content to honestly extract, so it was
excluded on that basis (no real content), independent of the license
question. The AGPL analysis for Countly in `docs/corpus_info.md` is
retained there as research history but doesn't correspond to anything in
`data/open_source_corpus/`.

## For the README / judge-facing copy

> We include one migration example from Mattermost's AGPLv3-licensed source
> in our training corpus, used only to study a real schema-migration
> pattern. We do not redistribute, host, or brand our project as a modified
> Mattermost service, and no Mattermost source or branding is shipped as
> part of this product.
