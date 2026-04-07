from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import src.config.config as config


ITEM_REPORT_GLOB = "*_items_*.json"
DB_FILENAME = "itemizer.db"


def get_reports_dir() -> Optional[Path]:
    if config.PG_BASE is None:
        return None
    return Path(config.PG_BASE) / "Reports"


def get_db_path() -> Path:
    return Path(config.DATA_DIR) / DB_FILENAME


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_name TEXT NOT NULL,
            character TEXT,
            server TEXT,
            timestamp TEXT,
            mtime REAL NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            item_name TEXT,
            type_id INTEGER,
            stack_size INTEGER,
            value INTEGER,
            rarity TEXT,
            slot TEXT,
            storage_vault TEXT,
            is_in_inventory INTEGER,
            level INTEGER,
            raw_json TEXT NOT NULL,
            search_text TEXT,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_reports_server ON reports(server);
        CREATE INDEX IF NOT EXISTS idx_reports_character ON reports(character);
        CREATE INDEX IF NOT EXISTS idx_items_report_id ON items(report_id);
        CREATE INDEX IF NOT EXISTS idx_items_item_name ON items(item_name);
        CREATE INDEX IF NOT EXISTS idx_items_search ON items(search_text);
        """
    )


def _compact_text(value, max_len=4000):
    parts = []

    def walk(obj):
        if len(" ".join(parts)) >= max_len:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif obj is not None:
            parts.append(str(obj))

    walk(value)
    return " ".join(parts)[:max_len]


def _read_report(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None

    items = payload.get("Items")
    if not isinstance(items, list):
        items = []

    character = payload.get("Character")
    server = payload.get("ServerName")
    timestamp = payload.get("Timestamp")
    return {
        "character": str(character) if character is not None else None,
        "server": str(server) if server is not None else None,
        "timestamp": str(timestamp) if timestamp is not None else None,
        "items": items,
    }


def _is_same_mtime(conn: sqlite3.Connection, file_path: Path, mtime: float) -> bool:
    cur = conn.execute("SELECT mtime FROM reports WHERE file_path = ?", (str(file_path),))
    row = cur.fetchone()
    if row is None:
        return False
    return abs(float(row[0]) - float(mtime)) < 0.0001


def _upsert_report(conn: sqlite3.Connection, file_path: Path, mtime: float, parsed: dict):
    conn.execute(
        """
        INSERT INTO reports (file_path, file_name, character, server, timestamp, mtime, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name=excluded.file_name,
            character=excluded.character,
            server=excluded.server,
            timestamp=excluded.timestamp,
            mtime=excluded.mtime,
            indexed_at=excluded.indexed_at
        """,
        (
            str(file_path),
            file_path.name,
            parsed.get("character"),
            parsed.get("server"),
            parsed.get("timestamp"),
            mtime,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    cur = conn.execute("SELECT id FROM reports WHERE file_path = ?", (str(file_path),))
    return int(cur.fetchone()[0])


def _replace_items(conn: sqlite3.Connection, report_id: int, items: list):
    conn.execute("DELETE FROM items WHERE report_id = ?", (report_id,))

    rows = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw = json.dumps(item, ensure_ascii=False)
        rows.append(
            (
                report_id,
                idx,
                item.get("Name"),
                item.get("TypeID"),
                item.get("StackSize"),
                item.get("Value"),
                item.get("Rarity"),
                item.get("Slot"),
                item.get("StorageVault"),
                1 if item.get("IsInInventory") else 0,
                item.get("Level"),
                raw,
                _compact_text(item),
            )
        )

    if rows:
        conn.executemany(
            """
            INSERT INTO items (
                report_id, row_index, item_name, type_id, stack_size, value, rarity, slot,
                storage_vault, is_in_inventory, level, raw_json, search_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def cleanup_orphaned_data(db_path: Optional[Path] = None):
    """Remove items and reports that no longer exist in the file system."""
    db_path = Path(db_path) if db_path else get_db_path()
    reports_dir = get_reports_dir()
    
    if not db_path.exists() or reports_dir is None or not reports_dir.exists():
        return {"cleaned_reports": 0, "cleaned_items": 0, "db_path": str(db_path)}
    
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        
        # Get all current report files in the directory
        current_files = {str(path) for path in sorted(reports_dir.glob(ITEM_REPORT_GLOB))}
        
        # Find and remove orphaned reports (no longer exist in filesystem)
        cursor = conn.execute("SELECT file_path FROM reports")
        db_files = {row[0] for row in cursor.fetchall()}
        orphaned_reports = db_files - current_files
        
        cleaned_reports = 0
        if orphaned_reports:
            placeholders = ",".join("?" for _ in orphaned_reports)
            conn.execute(f"DELETE FROM reports WHERE file_path IN ({placeholders})", tuple(orphaned_reports))
            cleaned_reports = len(orphaned_reports)
        
        # Clean up any orphaned items (should be handled by FK cascade, but let's be explicit)
        conn.execute("""
            DELETE FROM items 
            WHERE report_id NOT IN (
                SELECT id FROM reports 
                WHERE file_path IN ({})
            )
        """.format(",".join("?" for _ in current_files) if current_files else "''"), tuple(current_files))
        
        conn.commit()
        
    return {
        "cleaned_reports": cleaned_reports,
        "cleaned_items": conn.total_changes if hasattr(conn, 'total_changes') else 0,
        "db_path": str(db_path),
    }


def index_item_reports(reports_dir: Optional[Path] = None, db_path: Optional[Path] = None, force_refresh: bool = False):
    reports_dir = Path(reports_dir) if reports_dir else get_reports_dir()
    db_path = Path(db_path) if db_path else get_db_path()

    if reports_dir is None or not reports_dir.exists():
        return {"indexed_reports": 0, "skipped_reports": 0, "total_reports": 0, "db_path": str(db_path)}

    report_files = sorted(reports_dir.glob(ITEM_REPORT_GLOB))
    indexed = 0
    skipped = 0

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")

        # If force_refresh, clean up orphaned data first
        if force_refresh:
            cleanup_result = cleanup_orphaned_data(db_path)
            indexed = cleanup_result.get("cleaned_reports", 0)

        # Get current report files and remove ones that no longer exist
        seen_paths = {str(path) for path in report_files}
        conn.execute(
            "DELETE FROM reports WHERE file_path NOT IN ({})".format(
                ",".join("?" for _ in seen_paths) if seen_paths else "''"
            ),
            tuple(seen_paths),
        )

        for path in report_files:
            mtime = path.stat().st_mtime
            if _is_same_mtime(conn, path, mtime):
                skipped += 1
                continue

            try:
                parsed = _read_report(path)
                if parsed is None:
                    skipped += 1
                    continue
                report_id = _upsert_report(conn, path, mtime, parsed)
                _replace_items(conn, report_id, parsed.get("items", []))
                indexed += 1
            except Exception:
                skipped += 1

        conn.commit()

    result = {
        "indexed_reports": indexed,
        "skipped_reports": skipped,
        "total_reports": len(report_files),
        "db_path": str(db_path),
    }
    
    # Add cleanup info if force_refresh was used
    if force_refresh and 'cleanup_result' in locals():
        result["cleaned_reports"] = cleanup_result.get("cleaned_reports", 0)
        result["cleaned_items"] = cleanup_result.get("cleaned_items", 0)
    
    return result


def get_carried_item_names(server: str = "", character: str = "", db_path: Optional[Path] = None):
    """Return a sorted list of item names carried by the given character.

    "Carried" is defined as items that are flagged IsInInventory in the
    character's item report and whose StorageVault is either NULL/empty or
    looks like a saddle/saddlebag.
    """
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists() or not character:
        return []

    where = ["1=1", "i.is_in_inventory = 1"]
    params = []

    if server:
        where.append("r.server = ?")
        params.append(server)
    if character:
        where.append("r.character = ?")
        params.append(character)

    # Treat NULL/empty storage_vault as personal inventory; include saddles/bags.
    where.append("(i.storage_vault IS NULL OR i.storage_vault = '' OR i.storage_vault LIKE '%Saddle%')")

    where_sql = " AND ".join(where)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT DISTINCT i.item_name
            FROM items i
            JOIN reports r ON r.id = i.report_id
            WHERE {where_sql}
            ORDER BY i.item_name COLLATE NOCASE
            """,
            tuple(params),
        ).fetchall()

    return [row[0] for row in rows if row[0]]


def get_filter_values(db_path: Optional[Path] = None):
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists():
        return {"servers": [], "characters": []}

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        servers = [row[0] for row in conn.execute("SELECT DISTINCT server FROM reports WHERE server IS NOT NULL ORDER BY server")]
        characters = [
            row[0]
            for row in conn.execute("SELECT DISTINCT character FROM reports WHERE character IS NOT NULL ORDER BY character")
        ]
    return {"servers": servers, "characters": characters}


def search_items(
    server: str = "",
    character: str = "",
    text: str = "",
    limit: int = 250,
    offset: int = 0,
    db_path: Optional[Path] = None,
):
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists():
        return [], 0

    where = ["1=1"]
    params = []

    if server:
        where.append("r.server = ?")
        params.append(server)
    if character:
        where.append("r.character = ?")
        params.append(character)
    if text:
        where.append("(i.search_text LIKE ? OR i.item_name LIKE ?)")
        like = f"%{text}%"
        params.extend([like, like])

    where_sql = " AND ".join(where)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

        total = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM items i
                JOIN reports r ON r.id = i.report_id
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()[0]
        )

        rows = conn.execute(
            f"""
            SELECT
                r.server,
                r.character,
                r.timestamp,
                r.file_name,
                i.item_name,
                i.stack_size,
                i.value,
                i.rarity,
                i.slot,
                i.storage_vault,
                i.raw_json
            FROM items i
            JOIN reports r ON r.id = i.report_id
            WHERE {where_sql}
            ORDER BY r.server COLLATE NOCASE, r.character COLLATE NOCASE, i.item_name COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ).fetchall()

    results = [
        {
            "server": row[0] or "",
            "character": row[1] or "",
            "timestamp": row[2] or "",
            "file_name": row[3] or "",
            "item_name": row[4] or "",
            "stack_size": row[5] if row[5] is not None else "",
            "value": row[6] if row[6] is not None else "",
            "rarity": row[7] or "",
            "slot": row[8] or "",
            "storage_vault": row[9] or "",
            "raw_json": row[10],
        }
        for row in rows
    ]

    return results, total


def search_item_totals(
    server: str = "",
    character: str = "",
    text: str = "",
    db_path: Optional[Path] = None,
):
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists():
        return {"qty_total": 0, "value_total": 0}

    where = ["1=1"]
    params = []

    if server:
        where.append("r.server = ?")
        params.append(server)
    if character:
        where.append("r.character = ?")
        params.append(character)
    if text:
        where.append("(i.search_text LIKE ? OR i.item_name LIKE ?)")
        like = f"%{text}%"
        params.extend([like, like])

    where_sql = " AND ".join(where)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        qty_total, value_total = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN typeof(i.stack_size) IN ('integer', 'real') THEN i.stack_size ELSE 0 END), 0),
                COALESCE(
                    SUM(
                        (CASE WHEN typeof(i.value) IN ('integer', 'real') THEN i.value ELSE 0 END) *
                        (CASE WHEN typeof(i.stack_size) IN ('integer', 'real') THEN i.stack_size ELSE 0 END)
                    ),
                    0
                )
            FROM items i
            JOIN reports r ON r.id = i.report_id
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchone()

    return {"qty_total": int(qty_total or 0), "value_total": int(value_total or 0)}
