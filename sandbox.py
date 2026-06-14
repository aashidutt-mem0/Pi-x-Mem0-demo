"""
sandbox.py — creates a throwaway git repo for the demo to run pi against.

The @mem0/pi-agent-plugin derives its project app_id from `git rev-parse
--show-toplevel`. So for the cross-session story to be real, pi has to run
inside an actual git repository. This module makes one in a temp dir and seeds
it with a REAL existing schema + migrations whose conventions are NOT guessable.

Why a seeded schema matters: the demo's whole point is that a fresh agent
session cannot infer your team's conventions from nothing. So the sandbox ships
an existing schema that already encodes specific, opinionated choices:

  1. snake_case columns, but the PK is `<entity>_id` (not bare `id`)
  2. money stored as integer cents in a BIGINT column named `<thing>_cents`
     (never floats, never a `price`/`amount` DECIMAL)
  3. every table has `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  4. soft deletes via `deleted_at TIMESTAMPTZ` (nullable), never hard DELETE
  5. FKs are `<referenced_entity>_id` with an explicit ON DELETE RESTRICT
  6. migrations are raw SQL files named NNNN_description.sql, numbered, and
     must include a paired -- +migrate Down section (a real footgun if missed)

A fresh session with no memory will violate most of these. A session with the
decisions in Mem0 will match them. That contrast shows up as broken vs correct
SQL, not a wrong recital.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SANDBOX_ROOT = Path(os.environ.get("PI_DEMO_SANDBOX", "/tmp/pi-mem0-sandbox"))


# The conventions, as the developer would state them in Session 1. Kept here so
# the UI can pre-fill the decision box and the checker can verify against them.
SCHEMA_CONVENTIONS = """\
Schema and migration conventions for this service, follow them exactly:
1. Primary keys are named <entity>_id (e.g. order_id, refund_id), never a bare id.
2. Money is stored as integer cents in a BIGINT column named <thing>_cents. Never floats, never DECIMAL, never a column called price or amount.
3. Every table has created_at TIMESTAMPTZ NOT NULL DEFAULT now().
4. Deletes are soft: a nullable deleted_at TIMESTAMPTZ column. Never hard DELETE rows.
5. Foreign keys are named <referenced_entity>_id and declared ON DELETE RESTRICT.
6. Migrations are raw SQL files in migrations/ named NNNN_description.sql, sequentially numbered, and MUST include a paired '-- +migrate Down' section that reverses the change."""


# Machine-checkable rules: (label, regex that must be PRESENT in correct output,
# regex whose presence signals a VIOLATION). Used by checker.py.
CONVENTION_RULES = [
    {
        "id": "pk_naming",
        "label": "PK named <entity>_id, not bare id",
        "must_have": r"refund_id\b",
        "violation": r"\bid\s+(?:BIGINT|SERIAL|INT|UUID)\b(?![_a-z])",
    },
    {
        "id": "money_cents",
        "label": "Money as BIGINT <thing>_cents, never DECIMAL/float",
        "must_have": r"_cents\b\s+BIGINT",
        "violation": r"\b(?:DECIMAL|NUMERIC|FLOAT|REAL|MONEY)\b|\b(?:price|amount)\b",
    },
    {
        "id": "created_at",
        "label": "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "must_have": r"created_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+now\(\)",
        "violation": r"",
    },
    {
        "id": "soft_delete",
        "label": "Soft delete via nullable deleted_at",
        "must_have": r"deleted_at\s+TIMESTAMPTZ",
        "violation": r"",
    },
    {
        "id": "fk_restrict",
        "label": "FK <entity>_id ON DELETE RESTRICT",
        "must_have": r"REFERENCES\s+orders\s*\(\s*order_id\s*\).*?ON\s+DELETE\s+RESTRICT",
        "violation": r"ON\s+DELETE\s+CASCADE",
    },
    {
        "id": "down_migration",
        "label": "Paired -- +migrate Down section",
        "must_have": r"--\s*\+migrate\s+Down",
        "violation": r"",
    },
]


def ensure_sandbox() -> Path:
    """Create (idempotently) a git-backed sandbox project with a seeded schema."""
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

    if not (SANDBOX_ROOT / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=SANDBOX_ROOT, check=False)
        subprocess.run(["git", "config", "user.email", "demo@mem0.ai"], cwd=SANDBOX_ROOT, check=False)
        subprocess.run(["git", "config", "user.name", "Pi Mem0 Demo"], cwd=SANDBOX_ROOT, check=False)

    readme = SANDBOX_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Acme Checkout Service\n\n"
            "Payment and cart service for the Acme storefront. Postgres data layer, "
            "raw SQL migrations.\n"
        )

    # Seed an existing schema that encodes the conventions by example.
    migrations = SANDBOX_ROOT / "migrations"
    migrations.mkdir(exist_ok=True)

    m1 = migrations / "0001_create_orders.sql"
    if not m1.exists():
        m1.write_text(
            "-- +migrate Up\n"
            "CREATE TABLE orders (\n"
            "    order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,\n"
            "    customer_id     BIGINT NOT NULL,\n"
            "    total_cents     BIGINT NOT NULL,\n"
            "    currency        TEXT NOT NULL DEFAULT 'usd',\n"
            "    status          TEXT NOT NULL DEFAULT 'pending',\n"
            "    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),\n"
            "    deleted_at      TIMESTAMPTZ\n"
            ");\n\n"
            "-- +migrate Down\n"
            "DROP TABLE orders;\n"
        )

    m2 = migrations / "0002_create_line_items.sql"
    if not m2.exists():
        m2.write_text(
            "-- +migrate Up\n"
            "CREATE TABLE line_items (\n"
            "    line_item_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,\n"
            "    order_id        BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,\n"
            "    sku             TEXT NOT NULL,\n"
            "    quantity        INT NOT NULL,\n"
            "    unit_price_cents BIGINT NOT NULL,\n"
            "    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),\n"
            "    deleted_at      TIMESTAMPTZ\n"
            ");\n\n"
            "-- +migrate Down\n"
            "DROP TABLE line_items;\n"
        )

    # A schema doc that states intent but NOT every rule, so the agent still
    # needs the captured decisions (mirrors real repos: partial docs).
    schema_doc = SANDBOX_ROOT / "migrations" / "README.md"
    if not schema_doc.exists():
        schema_doc.write_text(
            "# Migrations\n\n"
            "Raw SQL, applied in order. Postgres. See existing files for the "
            "house style before adding new ones.\n"
        )

    return SANDBOX_ROOT


def git_root(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return str(path)


def app_id_for(path: Path) -> str:
    root = git_root(path)
    return os.path.basename(root)
