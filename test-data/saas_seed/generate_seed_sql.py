#!/usr/bin/env python3
"""Generate CockroachDB seed SQL for 10 real-world SaaS table schemas.

Ten tables, one per real open-source project (WordPress, Discourse, Gitea,
Chatwoot, Cal.com, Odoo, Medusa, PostHog, Redmine, Lago) — see
``00_schema_catalog.md`` in this directory for the source file each column
list was pulled from and citations for every table. This script only emits
SQL; it does not read anything at runtime, so column lists here ARE the
generator's source of truth, matching the catalog doc exactly.

Each table gets a plausible, typed row count under 10,000 (per the plan's
"under 10,000 rows" cap per table) of synthetic-but-type-correct data,
using only the Python standard library (no faker / pip install needed).

Usage (from repo root):
  python test-data/saas_seed/generate_seed_sql.py

Output: one ``NN_<table>.sql`` file per table in this directory, each a
self-contained CREATE TABLE + batched INSERT script, copy-paste-ready for
the CockroachDB Cloud SQL shell (same numbered-file convention as
test-data/irs_soi_zip_income/).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

OUT_DIR = Path(__file__).resolve().parent
RNG = random.Random(20260811)  # fixed seed -> reproducible output across runs
BATCH_SIZE = 500

# --------------------------------------------------------------------------
# Value generators (typed, stdlib-only)
# --------------------------------------------------------------------------

_WORDS = (
    "acme corp launch release migration schema index backfill customer "
    "invoice booking ticket topic partner product event issue conversation "
    "billing revenue growth pipeline dashboard workspace cluster shadow "
    "verify predict grade memory vector query table column payment "
    "subscription plan tenant region cockroach distributed replica leader"
).split()


def _word(n: int = 1) -> str:
    return " ".join(RNG.choice(_WORDS) for _ in range(n))


def sql_str(fn: Callable[[], str]) -> Callable[[int], str]:
    def _gen(_i: int) -> str:
        v = fn().replace("'", "''")
        return f"'{v}'"

    return _gen


def const_null(_i: int) -> str:
    return "NULL"


def maybe(gen: Callable[[int], str], null_rate: float = 0.25) -> Callable[[int], str]:
    def _gen(i: int) -> str:
        return "NULL" if RNG.random() < null_rate else gen(i)

    return _gen


def gen_seq_int(start: int = 1) -> Callable[[int], str]:
    def _gen(i: int) -> str:
        return str(start + i)

    return _gen


def gen_int(lo: int, hi: int) -> Callable[[int], str]:
    return lambda _i: str(RNG.randint(lo, hi))


def gen_bool(true_rate: float = 0.5) -> Callable[[int], str]:
    return lambda _i: "true" if RNG.random() < true_rate else "false"


def gen_decimal(lo: float, hi: float, places: int = 2) -> Callable[[int], str]:
    return lambda _i: f"{RNG.uniform(lo, hi):.{places}f}"


def gen_float(lo: float, hi: float, places: int = 6) -> Callable[[int], str]:
    return lambda _i: f"{RNG.uniform(lo, hi):.{places}f}"


def gen_uuid(_i: int) -> str:
    return f"'{uuid.UUID(int=RNG.getrandbits(128))}'"


def gen_text_id(prefix: str, nbytes: int = 13) -> Callable[[int], str]:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"

    def _gen(_i: int) -> str:
        token = "".join(RNG.choice(alphabet) for _ in range(nbytes))
        return f"'{prefix}_{token}'"

    return _gen


_EPOCH = datetime(2023, 1, 1, tzinfo=timezone.utc)
_SPAN_DAYS = 900


def _random_dt() -> datetime:
    return _EPOCH + timedelta(
        days=RNG.uniform(0, _SPAN_DAYS), seconds=RNG.randint(0, 86399)
    )


def gen_timestamp(_i: int) -> str:
    return f"'{_random_dt().strftime('%Y-%m-%d %H:%M:%S')}'"


def gen_date(_i: int) -> str:
    return f"'{_random_dt().strftime('%Y-%m-%d')}'"


def gen_unix_millis(_i: int) -> str:
    return str(int(_random_dt().timestamp()))


def gen_varchar(min_words: int, max_words: int) -> Callable[[int], str]:
    return sql_str(lambda: _word(RNG.randint(min_words, max_words)))


_booking_start_cache: dict[int, datetime] = {}


def gen_booking_start(i: int) -> str:
    dt = _random_dt()
    _booking_start_cache[i] = dt
    return f"'{dt.strftime('%Y-%m-%d %H:%M:%S')}'"


def gen_booking_end(i: int) -> str:
    # Paired with gen_booking_start via row index — keeps end_time strictly
    # after start_time so a derived duration_minutes column (the Block 5
    # demo migration) never comes out negative.
    start = _booking_start_cache[i]
    end = start + timedelta(minutes=RNG.randint(15, 240))
    return f"'{end.strftime('%Y-%m-%d %H:%M:%S')}'"


def gen_slug(_i: int) -> str:
    return f"'{_word(RNG.randint(2, 4)).replace(' ', '-')}-{RNG.randint(100, 999)}'"


def gen_email(_i: int) -> str:
    return f"'{_word(1)}.{RNG.randint(1, 9999)}@example.com'"


def gen_inet(_i: int) -> str:
    return f"'{RNG.randint(1, 223)}.{RNG.randint(0, 255)}.{RNG.randint(0, 255)}.{RNG.randint(1, 254)}'"


def gen_jsonb(keys: tuple[str, ...]) -> Callable[[int], str]:
    def _gen(_i: int) -> str:
        n = RNG.randint(0, len(keys))
        chosen = RNG.sample(keys, n)
        body = ", ".join(f'"{k}": "{_word(1)}"' for k in chosen)
        return f"'{{{body}}}'"

    return _gen


def gen_enum(*values: str) -> Callable[[int], str]:
    return lambda _i: f"'{RNG.choice(values)}'"


# --------------------------------------------------------------------------
# Schema model
# --------------------------------------------------------------------------


@dataclass
class Column:
    name: str
    crdb_type: str
    gen: Callable[[int], str]
    not_null: bool = False


@dataclass
class Table:
    name: str
    source_note: str
    pk: list[str]
    columns: list[Column]
    row_count: int

    def create_table_sql(self) -> str:
        lines = [f'CREATE TABLE "{self.name}" (']
        col_lines = []
        for c in self.columns:
            suffix = " NOT NULL" if c.not_null else ""
            col_lines.append(f'    "{c.name}" {c.crdb_type}{suffix}')
        pk_cols = ", ".join(f'"{p}"' for p in self.pk)
        col_lines.append(f"    PRIMARY KEY ({pk_cols})")
        lines.append(",\n".join(col_lines))
        lines.append(");")
        return "\n".join(lines)

    def insert_sql(self) -> str:
        col_names = ", ".join(f'"{c.name}"' for c in self.columns)
        rows = []
        for i in range(self.row_count):
            vals = ", ".join(c.gen(i) for c in self.columns)
            rows.append(f"({vals})")

        batches = []
        for start in range(0, len(rows), BATCH_SIZE):
            chunk = rows[start : start + BATCH_SIZE]
            batches.append(
                f'INSERT INTO "{self.name}" ({col_names}) VALUES\n'
                + ",\n".join(chunk)
                + ";"
            )
        return "\n\n".join(batches)

    def full_sql(self, file_index: int) -> str:
        header = (
            "-- =====================================================================\n"
            f"-- {self.name} — {self.source_note}\n"
            f"-- {self.row_count} rows of synthetic, type-correct data (real column\n"
            "-- names/types, generated values). See ../00_schema_catalog.md for the\n"
            "-- exact source file this schema was pulled from.\n"
            "--\n"
            "-- HOW TO USE:\n"
            "--   Paste this whole file into the CockroachDB Cloud SQL Shell and run it.\n"
            "--   No IMPORT INTO / external URL needed — plain batched INSERTs, so this\n"
            "--   works on every CockroachDB Cloud tier with no fetch/network step.\n"
            "-- =====================================================================\n"
        )
        return f"{header}\n{self.create_table_sql()}\n\n{self.insert_sql()}\n"


# --------------------------------------------------------------------------
# The 10 tables (columns/types sourced in 00_schema_catalog.md)
# --------------------------------------------------------------------------

TABLES: list[Table] = []

# 1. wp_posts — WordPress
TABLES.append(
    Table(
        name="wp_posts",
        source_note="WordPress src/wp-admin/includes/schema.php (wp_posts)",
        pk=["ID"],
        row_count=4000,
        columns=[
            Column("ID", "INT8", gen_seq_int(1), True),
            Column("post_author", "INT8", gen_int(1, 250), True),
            Column("post_date", "TIMESTAMP", gen_timestamp, True),
            Column("post_date_gmt", "TIMESTAMP", gen_timestamp, True),
            Column("post_content", "STRING", gen_varchar(20, 80), True),
            Column("post_title", "STRING", gen_varchar(3, 12), True),
            Column("post_excerpt", "STRING", gen_varchar(5, 20)),
            Column("post_status", "STRING(20)", gen_enum("publish", "draft", "pending", "private"), True),
            Column("comment_status", "STRING(20)", gen_enum("open", "closed"), True),
            Column("ping_status", "STRING(20)", gen_enum("open", "closed"), True),
            Column("post_password", "STRING(255)", maybe(sql_str(lambda: uuid.uuid4().hex[:12]), 0.9)),
            Column("post_name", "STRING(200)", gen_slug, True),
            Column("to_ping", "STRING", maybe(gen_varchar(1, 3), 0.8)),
            Column("pinged", "STRING", maybe(gen_varchar(1, 3), 0.8)),
            Column("post_modified", "TIMESTAMP", gen_timestamp, True),
            Column("post_modified_gmt", "TIMESTAMP", gen_timestamp, True),
            Column("post_content_filtered", "STRING", maybe(gen_varchar(5, 30), 0.7)),
            Column("post_parent", "INT8", gen_int(0, 50), True),
            Column("guid", "STRING(255)", sql_str(lambda: f"https://example.com/?p={RNG.randint(1, 9999)}"), True),
            Column("menu_order", "INT4", gen_int(0, 20), True),
            Column("post_type", "STRING(20)", gen_enum("post", "page", "attachment", "revision"), True),
            Column("post_mime_type", "STRING(100)", maybe(gen_enum("image/jpeg", "image/png", "application/pdf"), 0.6)),
            Column("comment_count", "INT8", gen_int(0, 400), True),
        ],
    )
)

# 2. discourse_topics — Discourse
TABLES.append(
    Table(
        name="discourse_topics",
        source_note="Discourse db/structure.sql (CREATE TABLE public.topics)",
        pk=["id"],
        row_count=3500,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("title", "STRING", gen_varchar(3, 10), True),
            Column("last_posted_at", "TIMESTAMP", maybe(gen_timestamp, 0.1)),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("updated_at", "TIMESTAMP", gen_timestamp, True),
            Column("views", "INT4", gen_int(0, 50000), True),
            Column("posts_count", "INT4", gen_int(1, 500), True),
            Column("user_id", "INT8", gen_int(1, 500), True),
            Column("last_post_user_id", "INT8", gen_int(1, 500), True),
            Column("reply_count", "INT4", gen_int(0, 300), True),
            Column("featured_user1_id", "INT8", maybe(gen_int(1, 500), 0.5)),
            Column("featured_user2_id", "INT8", maybe(gen_int(1, 500), 0.6)),
            Column("featured_user3_id", "INT8", maybe(gen_int(1, 500), 0.7)),
            Column("deleted_at", "TIMESTAMP", maybe(gen_timestamp, 0.95)),
            Column("highest_post_number", "INT4", gen_int(1, 500), True),
            Column("like_count", "INT4", gen_int(0, 2000), True),
            Column("incoming_link_count", "INT4", gen_int(0, 100), True),
            Column("category_id", "INT8", gen_int(1, 30), True),
            Column("visible", "BOOL", gen_bool(0.95), True),
            Column("moderator_posts_count", "INT4", gen_int(0, 20), True),
            Column("closed", "BOOL", gen_bool(0.1), True),
            Column("archived", "BOOL", gen_bool(0.05), True),
            Column("bumped_at", "TIMESTAMP", gen_timestamp, True),
            Column("has_summary", "BOOL", gen_bool(0.2), True),
            Column("archetype", "STRING", gen_enum("regular", "private_message", "banner"), True),
            Column("featured_user4_id", "INT8", maybe(gen_int(1, 500), 0.8)),
            Column("notify_moderators_count", "INT4", gen_int(0, 5), True),
            Column("spam_count", "INT4", gen_int(0, 3), True),
            Column("pinned_at", "TIMESTAMP", maybe(gen_timestamp, 0.9)),
            Column("score", "FLOAT8", gen_float(0, 500), True),
            Column("percent_rank", "FLOAT8", gen_float(0, 1), True),
            Column("subtype", "STRING", maybe(gen_varchar(1, 2), 0.8)),
            Column("slug", "STRING", gen_slug, True),
            Column("deleted_by_id", "INT8", maybe(gen_int(1, 500), 0.9)),
            Column("participant_count", "INT4", gen_int(1, 100), True),
            Column("word_count", "INT4", gen_int(10, 3000), True),
            Column("excerpt", "STRING", maybe(gen_varchar(5, 20), 0.3)),
            Column("pinned_globally", "BOOL", gen_bool(0.05), True),
            Column("pinned_until", "TIMESTAMP", maybe(gen_timestamp, 0.9)),
            Column("fancy_title", "STRING", gen_varchar(3, 10), True),
            Column("highest_staff_post_number", "INT4", gen_int(0, 500), True),
            Column("featured_link", "STRING", maybe(sql_str(lambda: "https://example.com/" + _word(1)), 0.8)),
            Column("reviewable_score", "FLOAT8", gen_float(0, 20), True),
            Column("image_upload_id", "INT8", maybe(gen_int(1, 9000), 0.6)),
            Column("slow_mode_seconds", "INT4", gen_int(0, 0), True),
            Column("bannered_until", "TIMESTAMP", maybe(gen_timestamp, 0.95)),
            Column("external_id", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:10]), 0.85)),
            Column("visibility_reason_id", "INT4", maybe(gen_int(1, 5), 0.9)),
            Column("locale", "STRING(20)", maybe(gen_enum("en", "es", "fr", "de", "ja"), 0.7)),
            Column("og_image_upload_id", "INT8", maybe(gen_int(1, 9000), 0.7)),
        ],
    )
)

# 3. gitea_issues — Gitea
TABLES.append(
    Table(
        name="gitea_issues",
        source_note="Gitea models/issues/issue.go (Issue struct, xorm-persisted fields)",
        pk=["id"],
        row_count=2500,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("repo_id", "INT8", gen_int(1, 80), True),
            Column("index", "INT8", gen_int(1, 5000), True),
            Column("poster_id", "INT8", gen_int(1, 400), True),
            Column("original_author", "STRING", maybe(gen_varchar(1, 2), 0.9)),
            Column("original_author_id", "INT8", maybe(gen_int(1, 400), 0.9)),
            Column("name", "STRING", gen_varchar(3, 10), True),
            Column("content", "STRING", gen_varchar(10, 60), True),
            Column("content_version", "INT4", gen_int(0, 5), True),
            Column("milestone_id", "INT8", maybe(gen_int(1, 50), 0.6)),
            Column("priority", "INT4", gen_int(0, 3), True),
            Column("is_closed", "BOOL", gen_bool(0.4), True),
            Column("is_pull", "BOOL", gen_bool(0.3), True),
            Column("ref", "STRING", maybe(sql_str(lambda: f"refs/heads/{_word(1)}"), 0.7)),
            Column("deadline_unix", "INT8", maybe(gen_unix_millis, 0.6)),
            Column("created_unix", "INT8", gen_unix_millis, True),
            Column("updated_unix", "INT8", gen_unix_millis, True),
            Column("closed_unix", "INT8", maybe(gen_unix_millis, 0.6)),
            Column("is_locked", "BOOL", gen_bool(0.05), True),
            Column("time_estimate", "INT8", gen_int(0, 144000), True),
        ],
    )
)

# 4. chatwoot_conversations — Chatwoot
TABLES.append(
    Table(
        name="chatwoot_conversations",
        source_note="Chatwoot db/schema.rb (create_table \"conversations\")",
        pk=["id"],
        row_count=3000,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("account_id", "INT8", gen_int(1, 40), True),
            Column("inbox_id", "INT8", gen_int(1, 60), True),
            Column("status", "INT4", gen_int(0, 2), True),
            Column("assignee_id", "INT8", maybe(gen_int(1, 300), 0.3)),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("updated_at", "TIMESTAMP", gen_timestamp, True),
            Column("contact_id", "INT8", gen_int(1, 2000), True),
            Column("display_id", "INT4", gen_seq_int(1), True),
            Column("contact_last_seen_at", "TIMESTAMP", maybe(gen_timestamp, 0.2)),
            Column("agent_last_seen_at", "TIMESTAMP", maybe(gen_timestamp, 0.2)),
            Column("additional_attributes", "JSONB", gen_jsonb(("browser", "referer", "plan", "utm_source")), True),
            Column("contact_inbox_id", "INT8", gen_int(1, 2000), True),
            Column("uuid", "UUID", gen_uuid, True),
            Column("identifier", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:16]), 0.7)),
            Column("last_activity_at", "TIMESTAMP", gen_timestamp, True),
            Column("team_id", "INT8", maybe(gen_int(1, 20), 0.4)),
            Column("campaign_id", "INT8", maybe(gen_int(1, 15), 0.85)),
            Column("snoozed_until", "TIMESTAMP", maybe(gen_timestamp, 0.9)),
            Column("custom_attributes", "JSONB", gen_jsonb(("plan", "priority_tier", "region")), True),
            Column("assignee_last_seen_at", "TIMESTAMP", maybe(gen_timestamp, 0.3)),
            Column("first_reply_created_at", "TIMESTAMP", maybe(gen_timestamp, 0.15)),
            Column("priority", "INT4", maybe(gen_int(0, 3), 0.5)),
            Column("sla_policy_id", "INT8", maybe(gen_int(1, 10), 0.8)),
            Column("waiting_since", "TIMESTAMP", maybe(gen_timestamp, 0.4)),
            Column("cached_label_list", "STRING", maybe(gen_varchar(1, 4), 0.5)),
            Column("assignee_agent_bot_id", "INT8", maybe(gen_int(1, 10), 0.9)),
            Column("status_changed_at", "TIMESTAMP", gen_timestamp, True),
        ],
    )
)

# 5. calcom_bookings — Cal.com
TABLES.append(
    Table(
        name="calcom_bookings",
        source_note="Cal.com packages/prisma/schema.prisma (model Booking, scalar/FK fields)",
        pk=["id"],
        row_count=4500,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("uid", "STRING", sql_str(lambda: uuid.uuid4().hex), True),
            Column("idempotency_key", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex), 0.6)),
            Column("user_id", "INT8", maybe(gen_int(1, 500), 0.05)),
            Column("user_primary_email", "STRING", maybe(gen_email, 0.3)),
            Column("event_type_id", "INT8", maybe(gen_int(1, 60), 0.1)),
            Column("title", "STRING", gen_varchar(3, 8), True),
            Column("description", "STRING", maybe(gen_varchar(5, 20), 0.4)),
            Column("custom_inputs", "JSONB", maybe(gen_jsonb(("phone", "notes")), 0.6)),
            Column("responses", "JSONB", gen_jsonb(("name", "email", "notes", "guests")), True),
            Column("start_time", "TIMESTAMP", gen_booking_start, True),
            Column("end_time", "TIMESTAMP", gen_booking_end, True),
            Column("location", "STRING", maybe(gen_enum("Zoom", "Google Meet", "Phone call", "In person"), 0.2)),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("updated_at", "TIMESTAMP", maybe(gen_timestamp, 0.2)),
            Column("status", "STRING", gen_enum("accepted", "pending", "cancelled", "rejected"), True),
            Column("paid", "BOOL", gen_bool(0.6), True),
            Column("destination_calendar_id", "INT8", maybe(gen_int(1, 100), 0.4)),
            Column("cancellation_reason", "STRING", maybe(gen_varchar(2, 8), 0.85)),
            Column("rejection_reason", "STRING", maybe(gen_varchar(2, 8), 0.9)),
            Column("reassign_reason", "STRING", maybe(gen_varchar(2, 8), 0.95)),
            Column("reassign_by_id", "INT8", maybe(gen_int(1, 500), 0.95)),
            Column("dynamic_event_slug_ref", "STRING", maybe(gen_slug, 0.8)),
            Column("dynamic_group_slug_ref", "STRING", maybe(gen_slug, 0.85)),
            Column("rescheduled", "BOOL", maybe(gen_bool(0.15), 0.5)),
            Column("from_reschedule", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex), 0.9)),
            Column("recurring_event_id", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:12]), 0.75)),
            Column("sms_reminder_number", "STRING", maybe(sql_str(lambda: f"+1{RNG.randint(2000000000, 9999999999)}"), 0.7)),
            Column("metadata", "JSONB", maybe(gen_jsonb(("videoCallUrl", "source")), 0.5)),
            Column("is_recorded", "BOOL", gen_bool(0.1), True),
            Column("ical_uid", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex + "@cal.com"), 0.2)),
            Column("ical_sequence", "INT4", gen_int(0, 5), True),
            Column("rating", "INT4", maybe(gen_int(1, 5), 0.7)),
            Column("rating_feedback", "STRING", maybe(gen_varchar(3, 10), 0.85)),
            Column("no_show_host", "BOOL", maybe(gen_bool(0.05), 0.6)),
            Column("one_time_password", "STRING", maybe(sql_str(lambda: str(RNG.randint(100000, 999999))), 0.9)),
            Column("cancelled_by", "STRING", maybe(gen_email, 0.85)),
            Column("rescheduled_by", "STRING", maybe(gen_email, 0.92)),
            Column("creation_source", "STRING", maybe(gen_enum("WEBAPP", "API_V1", "API_V2"), 0.4)),
        ],
    )
)

# 6. odoo_res_partner — Odoo
TABLES.append(
    Table(
        name="odoo_res_partner",
        source_note="Odoo odoo/addons/base/models/res_partner.py (res.partner, scalar + Many2one fields)",
        pk=["id"],
        row_count=5000,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("name", "STRING", sql_str(lambda: f"{_word(1).title()} {_word(1).title()}"), True),
            Column("complete_name", "STRING", sql_str(lambda: f"{_word(2).title()}"), True),
            Column("date", "DATE", maybe(gen_date, 0.5)),
            Column("title_id", "INT8", maybe(gen_int(1, 6), 0.6)),
            Column("parent_id", "INT8", maybe(gen_int(1, 4000), 0.5)),
            Column("ref", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:8]), 0.5)),
            Column("lang", "STRING", gen_enum("en_US", "fr_FR", "de_DE", "es_ES"), True),
            Column("active_lang_count", "INT4", gen_int(1, 3), True),
            Column("tz", "STRING", maybe(gen_enum("UTC", "America/New_York", "Europe/Paris"), 0.3)),
            Column("tz_offset", "STRING", gen_enum("+0000", "-0500", "+0100"), True),
            Column("user_id", "INT8", maybe(gen_int(1, 500), 0.6)),
            Column("vat", "STRING", maybe(sql_str(lambda: f"US{RNG.randint(100000000, 999999999)}"), 0.5)),
            Column("same_vat_partner_id", "INT8", maybe(gen_int(1, 4000), 0.95)),
            Column("same_company_registry_partner_id", "INT8", maybe(gen_int(1, 4000), 0.97)),
            Column("company_registry", "STRING", maybe(sql_str(lambda: str(RNG.randint(1000000, 9999999))), 0.6)),
            Column("website", "STRING", maybe(sql_str(lambda: f"https://{_word(1)}.com"), 0.4)),
            Column("comment", "STRING", maybe(gen_varchar(5, 20), 0.7)),
            Column("active", "BOOL", gen_bool(0.9), True),
            Column("employee", "BOOL", gen_bool(0.2), True),
            Column("function", "STRING", maybe(gen_enum("CEO", "Sales Manager", "Engineer", "Accountant"), 0.5)),
            Column("type", "STRING", gen_enum("contact", "invoice", "delivery", "other"), True),
            Column("street", "STRING", sql_str(lambda: f"{RNG.randint(1, 9999)} {_word(1).title()} St"), True),
            Column("street2", "STRING", maybe(gen_varchar(1, 3), 0.7)),
            Column("zip", "STRING", sql_str(lambda: f"{RNG.randint(10000, 99999)}"), True),
            Column("city", "STRING", sql_str(lambda: _word(1).title()), True),
            Column("state_id", "INT8", maybe(gen_int(1, 60), 0.3)),
            Column("country_id", "INT8", gen_int(1, 240), True),
            Column("partner_latitude", "FLOAT8", maybe(gen_float(-90, 90), 0.4)),
            Column("partner_longitude", "FLOAT8", maybe(gen_float(-180, 180), 0.4)),
            Column("email", "STRING", gen_email, True),
            Column("email_formatted", "STRING", gen_email, True),
            Column("phone", "STRING", maybe(sql_str(lambda: f"+1{RNG.randint(2000000000, 9999999999)}"), 0.2)),
            Column("mobile", "STRING", maybe(sql_str(lambda: f"+1{RNG.randint(2000000000, 9999999999)}"), 0.4)),
            Column("is_company", "BOOL", gen_bool(0.3), True),
            Column("is_public", "BOOL", gen_bool(0.05), True),
            Column("industry_id", "INT8", maybe(gen_int(1, 30), 0.5)),
            Column("company_type", "STRING", gen_enum("person", "company"), True),
            Column("company_id", "INT8", maybe(gen_int(1, 20), 0.3)),
            Column("color", "INT4", gen_int(0, 11), True),
            Column("partner_share", "BOOL", gen_bool(0.4), True),
            Column("contact_address", "STRING", gen_varchar(5, 15), True),
            Column("commercial_partner_id", "INT8", gen_int(1, 5000), True),
            Column("commercial_company_name", "STRING", maybe(sql_str(lambda: f"{_word(2).title()} Inc"), 0.6)),
            Column("company_name", "STRING", maybe(sql_str(lambda: f"{_word(2).title()} Inc"), 0.6)),
            Column("barcode", "STRING", maybe(sql_str(lambda: str(RNG.randint(1000000000000, 9999999999999))), 0.85)),
        ],
    )
)

# 7. medusa_products — Medusa
TABLES.append(
    Table(
        name="medusa_products",
        source_note="Medusa packages/modules/product/src/models/product.ts (+ BaseEntity timestamps)",
        pk=["id"],
        row_count=2000,
        columns=[
            Column("id", "STRING", gen_text_id("prod"), True),
            Column("title", "STRING", sql_str(lambda: f"{_word(2).title()}"), True),
            Column("handle", "STRING", gen_slug, True),
            Column("subtitle", "STRING", maybe(gen_varchar(1, 4), 0.5)),
            Column("description", "STRING", maybe(gen_varchar(10, 40), 0.2)),
            Column("is_giftcard", "BOOL", gen_bool(0.05), True),
            Column("status", "STRING", gen_enum("draft", "proposed", "published", "rejected"), True),
            Column("thumbnail", "STRING", maybe(sql_str(lambda: f"https://cdn.example.com/{uuid.uuid4().hex[:10]}.jpg"), 0.15)),
            Column("weight", "FLOAT8", maybe(gen_float(50, 5000, 1), 0.2)),
            Column("length", "FLOAT8", maybe(gen_float(1, 100, 1), 0.3)),
            Column("height", "FLOAT8", maybe(gen_float(1, 100, 1), 0.3)),
            Column("width", "FLOAT8", maybe(gen_float(1, 100, 1), 0.3)),
            Column("origin_country", "STRING", maybe(gen_enum("US", "CN", "DE", "VN", "IN"), 0.3)),
            Column("hs_code", "STRING", maybe(sql_str(lambda: str(RNG.randint(100000, 999999))), 0.7)),
            Column("mid_code", "STRING", maybe(sql_str(lambda: str(RNG.randint(1000, 9999))), 0.8)),
            Column("material", "STRING", maybe(gen_enum("cotton", "polyester", "aluminum", "plastic", "leather"), 0.4)),
            Column("discountable", "BOOL", gen_bool(0.85), True),
            Column("external_id", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:12]), 0.6)),
            Column("metadata", "JSONB", maybe(gen_jsonb(("vendor", "season", "sku_prefix")), 0.5)),
            Column("type_id", "STRING", maybe(gen_text_id("ptyp", 8), 0.3)),
            Column("collection_id", "STRING", maybe(gen_text_id("pcol", 8), 0.4)),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("updated_at", "TIMESTAMP", gen_timestamp, True),
            Column("deleted_at", "TIMESTAMP", maybe(gen_timestamp, 0.93)),
        ],
    )
)

# 8. posthog_events — PostHog
TABLES.append(
    Table(
        name="posthog_events",
        source_note="PostHog posthog/models/event/event.py + ClickHouse events table materialized columns",
        pk=["id"],
        row_count=8000,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("team_id", "INT8", gen_int(1, 30), True),
            Column("event", "STRING", gen_enum("$pageview", "$autocapture", "$identify", "signup_completed", "checkout_started"), True),
            Column("distinct_id", "STRING", sql_str(lambda: uuid.uuid4().hex[:16]), True),
            Column("properties", "JSONB", gen_jsonb(("plan", "$browser", "$os", "utm_campaign")), True),
            Column("timestamp", "TIMESTAMP", gen_timestamp, True),
            Column("elements_hash", "STRING", maybe(sql_str(lambda: uuid.uuid4().hex[:20]), 0.5)),
            Column("site_url", "STRING", sql_str(lambda: "https://app.example.com"), True),
            Column("elements", "JSONB", maybe(gen_jsonb(("tag", "text", "href")), 0.6)),
            Column("uuid", "UUID", gen_uuid, True),
            Column("person_id", "UUID", maybe(gen_uuid, 0.1)),
            Column("ip", "INET", gen_inet, True),
            Column("current_url", "STRING", sql_str(lambda: f"https://app.example.com/{_word(1)}"), True),
            Column("browser", "STRING", gen_enum("Chrome", "Safari", "Firefox", "Edge"), True),
            Column("os", "STRING", gen_enum("Mac OS X", "Windows", "Linux", "iOS", "Android"), True),
            Column("device_type", "STRING", gen_enum("Desktop", "Mobile", "Tablet"), True),
            Column("referrer", "STRING", maybe(sql_str(lambda: "https://google.com/search"), 0.4)),
            Column("session_id", "UUID", gen_uuid, True),
            Column("library", "STRING", gen_enum("web", "posthog-node", "posthog-python"), True),
            Column("library_version", "STRING", sql_str(lambda: f"1.{RNG.randint(0, 200)}.{RNG.randint(0, 9)}"), True),
        ],
    )
)

# 9. redmine_issues — Redmine
TABLES.append(
    Table(
        name="redmine_issues",
        source_note="Redmine app/models/issue.rb",
        pk=["id"],
        row_count=3000,
        columns=[
            Column("id", "INT8", gen_seq_int(1), True),
            Column("project_id", "INT8", gen_int(1, 50), True),
            Column("tracker_id", "INT8", gen_int(1, 5), True),
            Column("status_id", "INT8", gen_int(1, 8), True),
            Column("priority_id", "INT8", gen_int(1, 5), True),
            Column("author_id", "INT8", gen_int(1, 300), True),
            Column("assigned_to_id", "INT8", maybe(gen_int(1, 300), 0.3)),
            Column("category_id", "INT8", maybe(gen_int(1, 20), 0.4)),
            Column("fixed_version_id", "INT8", maybe(gen_int(1, 30), 0.5)),
            Column("parent_id", "INT8", maybe(gen_int(1, 2500), 0.7)),
            Column("root_id", "INT8", gen_int(1, 2500), True),
            Column("subject", "STRING(255)", gen_varchar(3, 12), True),
            Column("description", "STRING", maybe(gen_varchar(10, 60), 0.15)),
            Column("start_date", "DATE", maybe(gen_date, 0.2)),
            Column("due_date", "DATE", maybe(gen_date, 0.4)),
            Column("done_ratio", "INT4", gen_int(0, 100), True),
            Column("estimated_hours", "DECIMAL(10,2)", maybe(gen_decimal(1, 200), 0.5)),
            Column("is_private", "BOOL", gen_bool(0.1), True),
            Column("closed_on", "TIMESTAMP", maybe(gen_timestamp, 0.5)),
            Column("created_on", "TIMESTAMP", gen_timestamp, True),
            Column("updated_on", "TIMESTAMP", gen_timestamp, True),
            Column("lock_version", "INT4", gen_int(0, 10), True),
            Column("lft", "INT4", gen_seq_int(1), True),
            Column("rgt", "INT4", gen_seq_int(2), True),
        ],
    )
)

# 10. lago_invoices — Lago
TABLES.append(
    Table(
        name="lago_invoices",
        source_note="Lago app/models/invoice.rb (ActiveRecord schema annotation)",
        pk=["id"],
        row_count=6000,
        columns=[
            Column("id", "UUID", gen_uuid, True),
            Column("applied_grace_period", "INT4", gen_int(0, 30), True),
            Column("coupons_amount_cents", "INT8", gen_int(0, 500000), True),
            Column("credit_notes_amount_cents", "INT8", gen_int(0, 200000), True),
            Column("currency", "STRING", gen_enum("USD", "EUR", "GBP"), True),
            Column("expected_finalization_date", "DATE", maybe(gen_date, 0.5)),
            Column("fees_amount_cents", "INT8", gen_int(1000, 5000000), True),
            Column("file", "STRING", maybe(sql_str(lambda: f"invoices/{uuid.uuid4().hex}.pdf"), 0.3)),
            Column("finalized_at", "TIMESTAMP", maybe(gen_timestamp, 0.2)),
            Column("invoice_type", "INT4", gen_int(0, 4), True),
            Column("issuing_date", "DATE", gen_date, True),
            Column("net_payment_term", "INT4", lambda _i: str(RNG.choice([0, 15, 30, 45, 60])), True),
            Column("number", "STRING", sql_str(lambda: f"INV-{RNG.randint(100000, 999999)}"), True),
            Column("payment_attempts", "INT4", gen_int(0, 5), True),
            Column("payment_dispute_lost_at", "TIMESTAMP", maybe(gen_timestamp, 0.95)),
            Column("payment_due_date", "DATE", gen_date, True),
            Column("payment_overdue", "BOOL", gen_bool(0.1), True),
            Column("payment_status", "INT4", gen_int(0, 2), True),
            Column("prepaid_credit_amount_cents", "INT8", gen_int(0, 100000), True),
            Column("prepaid_granted_credit_amount_cents", "INT8", gen_int(0, 100000), True),
            Column("prepaid_purchased_credit_amount_cents", "INT8", gen_int(0, 100000), True),
            Column("progressive_billing_credit_amount_cents", "INT8", gen_int(0, 50000), True),
            Column("purchase_order_number", "STRING", maybe(sql_str(lambda: f"PO-{RNG.randint(1000, 9999)}"), 0.6)),
            Column("ready_for_payment_processing", "BOOL", gen_bool(0.9), True),
            Column("ready_to_be_refreshed", "BOOL", gen_bool(0.05), True),
            Column("self_billed", "BOOL", gen_bool(0.05), True),
            Column("skip_automatic_payment", "BOOL", gen_bool(0.1), True),
            Column("skip_charges", "BOOL", gen_bool(0.05), True),
            Column("status", "INT4", gen_int(0, 3), True),
            Column("sub_total_excluding_taxes_amount_cents", "INT8", gen_int(1000, 5000000), True),
            Column("sub_total_including_taxes_amount_cents", "INT8", gen_int(1000, 5500000), True),
            Column("tax_status", "STRING", maybe(gen_enum("pending", "succeeded", "failed"), 0.3)),
            Column("taxes_amount_cents", "INT8", gen_int(0, 500000), True),
            Column("taxes_rate", "FLOAT8", gen_float(0, 25, 2), True),
            Column("timezone", "STRING", gen_enum("UTC", "America/New_York", "Europe/London"), True),
            Column("total_amount_cents", "INT8", gen_int(1000, 6000000), True),
            Column("total_paid_amount_cents", "INT8", gen_int(0, 6000000), True),
            Column("version_number", "INT4", gen_int(1, 4), True),
            Column("voided_at", "TIMESTAMP", maybe(gen_timestamp, 0.95)),
            Column("xml_file", "STRING", maybe(sql_str(lambda: f"invoices/{uuid.uuid4().hex}.xml"), 0.9)),
            Column("created_at", "TIMESTAMP", gen_timestamp, True),
            Column("updated_at", "TIMESTAMP", gen_timestamp, True),
            Column("billing_entity_id", "UUID", gen_uuid, True),
            Column("customer_id", "UUID", gen_uuid, True),
            Column("organization_id", "UUID", gen_uuid, True),
            Column("payment_method_id", "UUID", maybe(gen_uuid, 0.3)),
            Column("sequential_id", "INT4", gen_seq_int(1), True),
            Column("voided_invoice_id", "UUID", maybe(gen_uuid, 0.95)),
        ],
    )
)


def main() -> None:
    for idx, table in enumerate(TABLES, start=1):
        RNG.seed(20260811 + idx)  # deterministic-but-distinct per table
        out_path = OUT_DIR / f"{idx:02d}_{table.name}.sql"
        out_path.write_text(table.full_sql(idx), encoding="utf-8", newline="\n")
        print(f"wrote {out_path.name}  ({table.row_count} rows, {len(table.columns)} cols)")


if __name__ == "__main__":
    main()
