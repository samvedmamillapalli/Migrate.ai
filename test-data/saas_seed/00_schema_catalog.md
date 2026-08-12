# Seed schema catalog — 10 real-world SaaS tables

Ten tables, each adapted from one real, well-known open-source project's
actual schema (fetched from the project's public migration files / model
definitions on 2026-08-11, not invented) — one domain each, so the seeded
database reads as a single plausible multi-tenant SaaS customer's Postgres
instance. Column counts range ~20-48 (not a uniform 40) because that's what
each real table actually has; padding was used sparingly and is called out
per-table below, per the block's "good enough, clearly real-shaped" bar.

Full column-level detail (name, CockroachDB type, generator strategy) lives
in `generate_seed_sql.py`; this doc is the source citation + column list.

| # | Table | Domain | Source project | Source file | Real cols | Notes |
|---|-------|--------|-----------------|--------------|-----------|-------|
| 1 | `wp_posts` | CMS content | WordPress | `wp-admin/includes/schema.php` | 23 | full real column set, no padding |
| 2 | `discourse_topics` | Forum | Discourse | `db/structure.sql` (`CREATE TABLE public.topics`) | 50 | full real column set (2 columns, `slug`/`external_id`, share a role between doc prose and script — count is exact in the generator) |
| 3 | `gitea_issues` | Issue tracker | Gitea | `models/issues/issue.go` (`Issue` struct, xorm tags) | 20 | persisted columns only (struct also has ~20 in-memory-only fields, excluded) |
| 4 | `chatwoot_conversations` | Support inbox | Chatwoot | `db/schema.rb` (`create_table "conversations"`) | 28 (27 real + implicit `id` PK) | Rails' implicit bigserial `id` isn't shown in the `t.` block but is a real column |
| 5 | `calcom_bookings` | Scheduling | Cal.com | `packages/prisma/schema.prisma` (`model Booking`) | 39 | scalar/FK columns only (relation-array fields excluded — those aren't real columns on `Booking`, they're the other side of a Prisma relation) |
| 6 | `odoo_res_partner` | CRM contacts | Odoo | `odoo/addons/base/models/res_partner.py` (`res.partner`) | 46 (44 real + implicit `id` PK + `same_company_registry_partner_id`) | scalar + Many2one (real FK column) fields; One2many/Many2many fields excluded (backed by other tables, not real columns on this one) |
| 7 | `medusa_products` | E-commerce catalog | Medusa | `packages/modules/product/src/models/product.ts` | 24 | 21 scalar/FK fields + `created_at`/`updated_at`/`deleted_at`, the standard timestamp columns Medusa's `BaseEntity` adds to every model (padding, clearly marked) |
| 8 | `posthog_events` | Product analytics | PostHog | `posthog/models/event/event.py` + PostHog's public ClickHouse `events` table schema | 21 | 10 real Postgres model fields + 11 columns (`uuid`, `person_id`, `ip`, `current_url`, `browser`, `os`, `device_type`, `referrer`, `session_id`, `library`, `library_version`) that mirror PostHog's actual ClickHouse `events` table materialized columns — real PostHog columns, just from the analytics store rather than the legacy Postgres model (padding, clearly marked) |
| 9 | `redmine_issues` | Project/issue tracker | Redmine | `app/models/issue.rb` | 24 | full real column set |
| 10 | `lago_invoices` | Billing (Stripe-style) | Lago | `app/models/invoice.rb` (ActiveRecord schema annotation) | 48 | full real column set |

Average ~32 columns/table (target was "near 40" — WordPress/Gitea/Medusa/
PostHog are the real reason the average sits below that; their actual
upstream schemas are simply narrower than a Discourse/Lago-style table).
Trimmed to stay honest to source rather than padded further, per the
block's own "accept good enough over perfect fidelity" instruction.

## 1. `wp_posts` — WordPress

Source: https://github.com/WordPress/wordpress-develop `src/wp-admin/includes/schema.php`

`ID` bigint unsigned · `post_author` bigint unsigned · `post_date` datetime ·
`post_date_gmt` datetime · `post_content` longtext · `post_title` text ·
`post_excerpt` text · `post_status` varchar(20) · `comment_status`
varchar(20) · `ping_status` varchar(20) · `post_password` varchar(255) ·
`post_name` varchar(200) · `to_ping` text · `pinged` text · `post_modified`
datetime · `post_modified_gmt` datetime · `post_content_filtered` longtext ·
`post_parent` bigint unsigned · `guid` varchar(255) · `menu_order` int ·
`post_type` varchar(20) · `post_mime_type` varchar(100) · `comment_count`
bigint

PK: `ID` (natural grain — WordPress's own auto-increment post id).

## 2. `discourse_topics` — Discourse

Source: https://github.com/discourse/discourse `db/structure.sql`, `CREATE TABLE public.topics`

`id` integer · `title` varchar · `last_posted_at` timestamp ·
`created_at` timestamp · `updated_at` timestamp · `views` integer ·
`posts_count` integer · `user_id` integer · `last_post_user_id` integer ·
`reply_count` integer · `featured_user1_id` integer · `featured_user2_id`
integer · `featured_user3_id` integer · `deleted_at` timestamp ·
`highest_post_number` integer · `like_count` integer ·
`incoming_link_count` integer · `category_id` integer · `visible` boolean ·
`moderator_posts_count` integer · `closed` boolean · `archived` boolean ·
`bumped_at` timestamp · `has_summary` boolean · `archetype` varchar ·
`featured_user4_id` integer · `notify_moderators_count` integer ·
`spam_count` integer · `pinned_at` timestamp · `score` double precision ·
`percent_rank` double precision · `subtype` varchar · `slug` varchar ·
`deleted_by_id` integer · `participant_count` integer · `word_count`
integer · `excerpt` varchar · `pinned_globally` boolean · `pinned_until`
timestamp · `fancy_title` varchar · `highest_staff_post_number` integer ·
`featured_link` varchar · `reviewable_score` double precision ·
`image_upload_id` bigint · `slow_mode_seconds` integer · `bannered_until`
timestamp · `external_id` varchar · `visibility_reason_id` integer ·
`locale` varchar(20) · `og_image_upload_id` bigint

PK: `id` (natural grain).

## 3. `gitea_issues` — Gitea

Source: https://github.com/go-gitea/gitea `models/issues/issue.go`, `Issue` struct (xorm-tagged fields only)

`id` int64 pk · `repo_id` int64 · `index` int64 · `poster_id` int64 ·
`original_author` string · `original_author_id` int64 · `name` string
(the `Title` field, db column `name`) · `content` text ·
`content_version` int · `milestone_id` int64 · `priority` int ·
`is_closed` bool · `is_pull` bool · `ref` string · `deadline_unix` bigint ·
`created_unix` bigint · `updated_unix` bigint · `closed_unix` bigint ·
`is_locked` bool · `time_estimate` bigint

PK: `id` (natural grain).

## 4. `chatwoot_conversations` — Chatwoot

Source: https://github.com/chatwoot/chatwoot `db/schema.rb`, `create_table "conversations"`

`account_id` integer · `inbox_id` integer · `status` integer ·
`assignee_id` integer · `created_at` datetime · `updated_at` datetime ·
`contact_id` bigint · `display_id` integer · `contact_last_seen_at`
datetime · `agent_last_seen_at` datetime · `additional_attributes` jsonb ·
`contact_inbox_id` bigint · `uuid` uuid · `identifier` string ·
`last_activity_at` datetime · `team_id` bigint · `campaign_id` bigint ·
`snoozed_until` datetime · `custom_attributes` jsonb ·
`assignee_last_seen_at` datetime · `first_reply_created_at` datetime ·
`priority` integer · `sla_policy_id` bigint · `waiting_since` datetime ·
`cached_label_list` text · `assignee_agent_bot_id` bigint ·
`status_changed_at` datetime

PK: `id` (bigserial, implicit Rails PK, not shown in the `t.` block — natural grain).

## 5. `calcom_bookings` — Cal.com

Source: https://github.com/calcom/cal.com `packages/prisma/schema.prisma`, `model Booking` (scalar/FK fields)

`id` int pk · `uid` string · `idempotency_key` string? · `user_id` int? ·
`user_primary_email` string? · `event_type_id` int? · `title` string ·
`description` string? · `custom_inputs` json? · `responses` json? ·
`start_time` timestamp · `end_time` timestamp · `location` string? ·
`created_at` timestamp · `updated_at` timestamp? · `status` string
(enum `BookingStatus`) · `paid` boolean · `destination_calendar_id` int? ·
`cancellation_reason` string? · `rejection_reason` string? ·
`reassign_reason` string? · `reassign_by_id` int? ·
`dynamic_event_slug_ref` string? · `dynamic_group_slug_ref` string? ·
`rescheduled` boolean? · `from_reschedule` string? · `recurring_event_id`
string? · `sms_reminder_number` string? · `metadata` json? ·
`is_recorded` boolean · `ical_uid` string? · `ical_sequence` int ·
`rating` int? · `rating_feedback` string? · `no_show_host` boolean? ·
`one_time_password` string? · `cancelled_by` string? · `rescheduled_by`
string? · `creation_source` string?

PK: `id` (natural grain).

## 6. `odoo_res_partner` — Odoo

Source: https://github.com/odoo/odoo `odoo/addons/base/models/res_partner.py`, `res.partner` (scalar + Many2one FK fields; One2many/Many2many excluded — not real columns on this table)

`name` char · `complete_name` char · `date` date · `title_id` (Many2one
`res.partner.title`) · `parent_id` (Many2one `res.partner`) · `ref` char ·
`lang` char · `active_lang_count` integer · `tz` char · `tz_offset` char ·
`user_id` (Many2one `res.users`) · `vat` char · `same_vat_partner_id`
(Many2one) · `same_company_registry_partner_id` (Many2one) ·
`company_registry` char · `website` char · `comment` html · `active`
boolean · `employee` boolean · `function` char · `type` selection ·
`street` char · `street2` char · `zip` char · `city` char · `state_id`
(Many2one `res.country.state`) · `country_id` (Many2one `res.country`) ·
`partner_latitude` float · `partner_longitude` float · `email` char ·
`email_formatted` char · `phone` char · `mobile` char · `is_company`
boolean · `is_public` boolean · `industry_id` (Many2one
`res.partner.industry`) · `company_type` selection · `company_id`
(Many2one `res.company`) · `color` integer · `partner_share` boolean ·
`contact_address` char · `commercial_partner_id` (Many2one) ·
`commercial_company_name` char · `company_name` char · `barcode` char

PK: `id` (Odoo's standard implicit integer PK, natural grain).

## 7. `medusa_products` — Medusa

Source: https://github.com/medusajs/medusa `packages/modules/product/src/models/product.ts` (scalar/FK fields) + Medusa's `BaseEntity` timestamp columns (padding, marked)

`id` text pk (Medusa's `prod_...` prefixed id) · `title` text · `handle`
text · `subtitle` text? · `description` text? · `is_giftcard` boolean ·
`status` text (enum `ProductStatus`) · `thumbnail` text? · `weight`
float? · `length` float? · `height` float? · `width` float? ·
`origin_country` text? · `hs_code` text? · `mid_code` text? · `material`
text? · `discountable` boolean · `external_id` text? · `metadata` json? ·
`type_id` text? (belongsTo `ProductType`) · `collection_id` text?
(belongsTo `ProductCollection`) · `created_at` timestamp *(padding —
`BaseEntity` standard column)* · `updated_at` timestamp *(padding)* ·
`deleted_at` timestamp? *(padding)*

PK: `id` (natural grain — Medusa's own prefixed text id, not a synthetic addition).

## 8. `posthog_events` — PostHog

Source: https://github.com/PostHog/posthog `posthog/models/event/event.py` (legacy Postgres `Event` model) + PostHog's public ClickHouse `events` table schema (materialized-property columns, padding, marked)

`id` bigserial pk · `created_at` timestamp · `team_id` (FK) · `event`
varchar · `distinct_id` varchar · `properties` jsonb · `timestamp`
timestamp · `elements_hash` varchar · `site_url` varchar · `elements`
jsonb · `uuid` uuid *(padding — ClickHouse events table)* · `person_id`
uuid *(padding)* · `ip` inet *(padding)* · `current_url` text *(padding)*
· `browser` varchar *(padding)* · `os` varchar *(padding)* ·
`device_type` varchar *(padding)* · `referrer` text *(padding)* ·
`session_id` uuid *(padding)* · `library` varchar *(padding)* ·
`library_version` varchar *(padding)*

PK: `id` (natural grain for the Postgres-side model).

## 9. `redmine_issues` — Redmine

Source: https://github.com/redmine/redmine `app/models/issue.rb`

`id` integer pk · `project_id` integer · `tracker_id` integer ·
`status_id` integer · `priority_id` integer · `author_id` integer ·
`assigned_to_id` integer · `category_id` integer · `fixed_version_id`
integer · `parent_id` integer · `root_id` integer · `subject` string(255)
· `description` text · `start_date` date · `due_date` date · `done_ratio`
integer · `estimated_hours` decimal · `is_private` boolean · `closed_on`
datetime · `created_on` datetime · `updated_on` datetime · `lock_version`
integer · `lft` integer · `rgt` integer

PK: `id` (natural grain).

## 10. `lago_invoices` — Lago

Source: https://github.com/getlago/lago-api `app/models/invoice.rb` (ActiveRecord schema annotation comment)

`id` uuid pk · `applied_grace_period` integer · `coupons_amount_cents`
bigint · `credit_notes_amount_cents` bigint · `currency` string ·
`expected_finalization_date` date · `fees_amount_cents` bigint · `file`
string · `finalized_at` timestamp · `invoice_type` integer ·
`issuing_date` date · `net_payment_term` integer · `number` string ·
`payment_attempts` integer · `payment_dispute_lost_at` timestamp ·
`payment_due_date` date · `payment_overdue` boolean · `payment_status`
integer · `prepaid_credit_amount_cents` bigint ·
`prepaid_granted_credit_amount_cents` bigint ·
`prepaid_purchased_credit_amount_cents` bigint ·
`progressive_billing_credit_amount_cents` bigint · `purchase_order_number`
string · `ready_for_payment_processing` boolean · `ready_to_be_refreshed`
boolean · `self_billed` boolean · `skip_automatic_payment` boolean ·
`skip_charges` boolean · `status` integer ·
`sub_total_excluding_taxes_amount_cents` bigint ·
`sub_total_including_taxes_amount_cents` bigint · `tax_status` string
(enum) · `taxes_amount_cents` bigint · `taxes_rate` float · `timezone`
string · `total_amount_cents` bigint · `total_paid_amount_cents` bigint ·
`version_number` integer · `voided_at` timestamp · `xml_file` string ·
`created_at` timestamp · `updated_at` timestamp · `billing_entity_id`
uuid · `customer_id` uuid · `organization_id` uuid · `payment_method_id`
uuid · `sequential_id` integer · `voided_invoice_id` uuid

PK: `id` (natural grain — Lago uses UUID PKs throughout).

## Judgment calls

- **One table per domain, not both listed** (e.g. Discourse `topics` not
  `users`, Chatwoot `conversations` not `contacts`) — picked whichever of
  the pair was wider/more visually interesting for a demo backfill, per
  Block 5's needs.
- **Padding kept minimal and always labeled** (`gitea_issues`,
  `medusa_products`, `posthog_events`) rather than inventing columns to
  force every table to exactly ~40 — truthfulness to the real source beat
  hitting a round number, matching the block's own tiebreaker instruction.
- **Target: a separate CockroachDB database on the same cluster
  (`demo_saas_seed`)**, not the app's own `migration_oracle` control-plane
  database — these tables are the thing a user's connection points *at*,
  not part of the app's own schema, and app control-plane data must not be
  touched. See Block 4 for the load run against that database.
