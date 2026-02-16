from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import Origin


@dataclass(frozen=True)
class MappingRow:
    outlook_id: str
    google_id: str
    origin: Origin
    last_outlook_fp: str = ""
    last_google_fp: str = ""
    last_outlook_modified: str = ""
    last_google_updated: str = ""


class MappingStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mapping (
              outlook_id TEXT NOT NULL,
              google_id  TEXT NOT NULL,
              origin TEXT NOT NULL DEFAULT 'outlook',
              last_outlook_fp TEXT NOT NULL DEFAULT '',
              last_google_fp  TEXT NOT NULL DEFAULT '',
              last_outlook_modified TEXT NOT NULL DEFAULT '',
              last_google_updated   TEXT NOT NULL DEFAULT '',
              PRIMARY KEY (outlook_id, google_id)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
              k TEXT PRIMARY KEY,
              v TEXT NOT NULL
            );
            """
        )
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(mapping);").fetchall()]
        if "origin" not in cols:
            cur.execute("ALTER TABLE mapping ADD COLUMN origin TEXT NOT NULL DEFAULT 'outlook';")
        self._conn.commit()

    def _row_to_mapping(self, row: sqlite3.Row) -> MappingRow:
        raw = dict(row)
        origin_raw = str(raw.get("origin", "outlook"))
        origin: Origin = "google" if origin_raw == "google" else "outlook"
        return MappingRow(
            outlook_id=str(raw["outlook_id"]),
            google_id=str(raw["google_id"]),
            origin=origin,
            last_outlook_fp=str(raw.get("last_outlook_fp", "")),
            last_google_fp=str(raw.get("last_google_fp", "")),
            last_outlook_modified=str(raw.get("last_outlook_modified", "")),
            last_google_updated=str(raw.get("last_google_updated", "")),
        )

    def get_by_outlook(self, outlook_id: str) -> MappingRow | None:
        cur = self._conn.cursor()
        row = cur.execute("SELECT * FROM mapping WHERE outlook_id = ?", (outlook_id,)).fetchone()
        if not row:
            return None
        return self._row_to_mapping(row)

    def get_by_google(self, google_id: str) -> MappingRow | None:
        cur = self._conn.cursor()
        row = cur.execute("SELECT * FROM mapping WHERE google_id = ?", (google_id,)).fetchone()
        if not row:
            return None
        return self._row_to_mapping(row)

    def list_all(self) -> list[MappingRow]:
        cur = self._conn.cursor()
        rows = cur.execute("SELECT * FROM mapping").fetchall()
        return [self._row_to_mapping(row) for row in rows]

    def upsert(self, m: MappingRow) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO mapping(outlook_id, google_id, origin, last_outlook_fp, last_google_fp, last_outlook_modified, last_google_updated)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(outlook_id, google_id) DO UPDATE SET
              origin=excluded.origin,
              last_outlook_fp=excluded.last_outlook_fp,
              last_google_fp=excluded.last_google_fp,
              last_outlook_modified=excluded.last_outlook_modified,
              last_google_updated=excluded.last_google_updated
            """,
            (
                m.outlook_id,
                m.google_id,
                m.origin,
                m.last_outlook_fp,
                m.last_google_fp,
                m.last_outlook_modified,
                m.last_google_updated,
            ),
        )
        self._conn.commit()

    def delete_pair(self, outlook_id: str, google_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM mapping WHERE outlook_id=? AND google_id=?", (outlook_id, google_id)
        )
        self._conn.commit()

    def delete_by_outlook(self, outlook_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM mapping WHERE outlook_id=?", (outlook_id,))
        self._conn.commit()

    def delete_by_google(self, google_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM mapping WHERE google_id=?", (google_id,))
        self._conn.commit()

    def kv_get(self, k: str) -> str | None:
        cur = self._conn.cursor()
        row = cur.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def kv_set(self, k: str, v: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v),
        )
        self._conn.commit()
