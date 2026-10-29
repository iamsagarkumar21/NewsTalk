"""
Versioned schema migrations for NewsTalk SQLite database.
Applied in order, each migration is idempotent.
"""
from __future__ import annotations

import datetime
from collections.abc import Callable

from sqlalchemy import Engine, text


def _ensure_migrations_table(engine: Engine):
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  name TEXT NOT NULL,"
            "  applied_at DATETIME NOT NULL DEFAULT (datetime('now'))"
            ")"
        ))
        conn.commit()


def _already_applied(engine: Engine, version: int) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :v"),
            {"v": version},
        ).fetchone()
        return row is not None


def _record_migration(engine: Engine, version: int, name: str):
    with engine.connect() as conn:
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (:v, :n)"),
            {"v": version, "n": name},
        )
        conn.commit()


# ── migration definitions ──────────────────────────────────────────

def _migration_v1_latest_article_at(engine: Engine):
    """Add latest_article_at column to story_clusters (original migration)."""
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(story_clusters)")).fetchall()
        cols = {r[1] for r in rows}
        if "latest_article_at" not in cols:
            conn.execute(text(
                "ALTER TABLE story_clusters ADD COLUMN latest_article_at DATETIME"
            ))
            conn.commit()


def _migration_v2_event_model(engine: Engine):
    """Add event-tracking, source-tier, and dynamic-briefing columns."""
    with engine.connect() as conn:
        # Check each column independently (idempotent)
        for table, col, coldef in [
            ("raw_articles", "tier", "INTEGER DEFAULT 4"),
            ("raw_articles", "embedding", "BLOB"),
            ("raw_articles", "canonical_key", "TEXT"),
            ("story_clusters", "event_started_at", "DATETIME"),
            ("story_clusters", "latest_development_at", "DATETIME"),
            ("story_clusters", "development_count", "INTEGER DEFAULT 0"),
            ("story_clusters", "last_change_kind", "TEXT"),
            ("story_clusters", "india_relevance", "FLOAT DEFAULT 0.0"),
            ("story_clusters", "source_tiers_json", "TEXT"),
            ("story_clusters", "conflicts_json", "TEXT"),
            ("briefings", "story_count", "INTEGER"),
            ("briefings", "is_quiet_day", "INTEGER DEFAULT 0"),
        ]:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            cols = {r[1] for r in rows}
            if col not in cols:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {col} {coldef}"
                ))

        # Indexes
        existing_indexes = {
            r[0]
            for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )).fetchall()
        }
        for idx_name, idx_ddl in [
            ("idx_raw_articles_canonical_key",
             "CREATE INDEX idx_raw_articles_canonical_key ON raw_articles(canonical_key)"),
            ("idx_raw_articles_fetched_at",
             "CREATE INDEX idx_raw_articles_fetched_at ON raw_articles(fetched_at)"),
        ]:
            if idx_name not in existing_indexes:
                conn.execute(text(idx_ddl))

        conn.commit()


def _migration_v3_per_user(engine: Engine):
    """Scope briefings, Q&A and memory to users; legacy rows go to the owner user (id=1).

    New tables come from create_all(); this only fixes tables that already existed.
    SQLite-specific, like v1/v2 (table rebuild is needed to change user_memory's key).
    """
    with engine.begin() as conn:
        owner = conn.execute(text("SELECT 1 FROM users WHERE id = 1")).fetchone()
        if not owner:
            conn.execute(
                text(
                    "INSERT INTO users (id, auth_provider, created_at) "
                    "VALUES (1, 'owner', :now)"
                ),
                {"now": datetime.datetime.utcnow()},
            )

        for table in ("briefings", "qa_log"):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if "user_id" not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
            conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))

        mem_cols = {
            r[1] for r in conn.execute(text("PRAGMA table_info(user_memory)")).fetchall()
        }
        if "user_id" not in mem_cols:
            conn.execute(text("ALTER TABLE user_memory RENAME TO user_memory_old"))
            conn.execute(
                text(
                    "CREATE TABLE user_memory ("
                    " user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,"
                    " topic VARCHAR NOT NULL,"
                    " familiarity_level FLOAT NOT NULL,"
                    " last_covered_at DATETIME,"
                    " notes TEXT,"
                    " PRIMARY KEY (user_id, topic))"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO user_memory "
                    "(user_id, topic, familiarity_level, last_covered_at, notes) "
                    "SELECT 1, topic, familiarity_level, last_covered_at, notes "
                    "FROM user_memory_old"
                )
            )
            conn.execute(text("DROP TABLE user_memory_old"))


# ── migration registry ─────────────────────────────────────────────

MIGRATIONS: list[tuple[int, str, Callable[[Engine], None]]] = [
    (1, "add_latest_article_at", _migration_v1_latest_article_at),
    (2, "event_model_v2", _migration_v2_event_model),
    (3, "per_user_scoping", _migration_v3_per_user),
]

MIGRATIONS.sort(key=lambda m: m[0])


# ── public API ─────────────────────────────────────────────────────

def migrate(engine: Engine):
    """Apply all pending migrations idempotently."""
    _ensure_migrations_table(engine)
    for version, name, fn in MIGRATIONS:
        if _already_applied(engine, version):
            continue
        fn(engine)
        _record_migration(engine, version, name)
