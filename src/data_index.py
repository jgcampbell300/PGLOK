import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_FILENAME = "pglok_index.db"


def get_db_path(data_dir):
    return Path(data_dir) / DB_FILENAME


def ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS file_index (
            filename TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            row_count INTEGER NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS data_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            row_index INTEGER,
            row_key TEXT,
            payload TEXT NOT NULL,
            search_text TEXT,
            FOREIGN KEY(filename) REFERENCES file_index(filename)
        );

        CREATE INDEX IF NOT EXISTS idx_data_rows_filename ON data_rows(filename);
        CREATE INDEX IF NOT EXISTS idx_data_rows_filename_row_index ON data_rows(filename, row_index);
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
    text = " ".join(parts)
    return text[:max_len]


def _iter_rows(document):
    if isinstance(document, list):
        for idx, item in enumerate(document):
            yield idx, None, item
        return

    if isinstance(document, dict):
        for idx, (key, value) in enumerate(document.items()):
            yield idx, str(key), value
        return

    yield 0, None, document


def _index_file(conn, file_path):
    filename = file_path.name
    mtime = file_path.stat().st_mtime

    cur = conn.execute("SELECT mtime FROM file_index WHERE filename = ?", (filename,))
    row = cur.fetchone()
    if row and abs(float(row[0]) - float(mtime)) < 0.0001:
        return 0, False

    with file_path.open("r", encoding="utf-8") as f:
        document = json.load(f)

    conn.execute("DELETE FROM data_rows WHERE filename = ?", (filename,))

    insert_rows = []
    row_count = 0
    for row_index, row_key, value in _iter_rows(document):
        payload = json.dumps(value, ensure_ascii=False)
        search_text = _compact_text({row_key: value} if row_key is not None else value)
        insert_rows.append((filename, row_index, row_key, payload, search_text))
        row_count += 1

    conn.executemany(
        """
        INSERT INTO data_rows (filename, row_index, row_key, payload, search_text)
        VALUES (?, ?, ?, ?, ?)
        """,
        insert_rows,
    )

    conn.execute(
        """
        INSERT INTO file_index (filename, mtime, row_count, indexed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            mtime=excluded.mtime,
            row_count=excluded.row_count,
            indexed_at=excluded.indexed_at
        """,
        (filename, mtime, row_count, datetime.now(timezone.utc).isoformat()),
    )

    return row_count, True


def index_data_dir(data_dir, db_path=None):
    data_dir = Path(data_dir)
    db_path = Path(db_path) if db_path else get_db_path(data_dir)

    indexed_files = 0
    skipped_files = 0

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

        json_files = sorted(data_dir.glob("*.json"))
        for file_path in json_files:
            row_count, updated = _index_file(conn, file_path)
            if updated:
                indexed_files += 1
            else:
                skipped_files += 1

        conn.commit()

    return {
        "db_path": str(db_path),
        "indexed_files": indexed_files,
        "skipped_files": skipped_files,
        "total_files": len(sorted(data_dir.glob("*.json"))),
    }


def list_indexed_files(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.execute(
            """
            SELECT filename, row_count, indexed_at
            FROM file_index
            ORDER BY filename COLLATE NOCASE
            """
        )
        return [
            {
                "filename": row[0],
                "row_count": row[1],
                "indexed_at": row[2],
            }
            for row in cur.fetchall()
        ]


def fetch_rows(db_path, filename, search_text="", limit=200, offset=0):
    db_path = Path(db_path)
    if not db_path.exists():
        return [], 0

    where = "filename = ?"
    params = [filename]

    if search_text:
        where += " AND search_text LIKE ?"
        params.append(f"%{search_text}%")

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

        count_cur = conn.execute(f"SELECT COUNT(*) FROM data_rows WHERE {where}", params)
        total = int(count_cur.fetchone()[0])

        rows_cur = conn.execute(
            f"""
            SELECT row_index, row_key, payload
            FROM data_rows
            WHERE {where}
            ORDER BY row_index
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        )

        rows = [
            {
                "row_index": row[0],
                "row_key": row[1],
                "payload": row[2],
            }
            for row in rows_cur.fetchall()
        ]

    return rows, total
