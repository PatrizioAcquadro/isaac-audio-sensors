"""Durable recorder state and bounded producer-ID index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from isaac_audio_sensors.recording._atomic import write_json_atomic


class RecoveryStore:
    def __init__(self, staging_root: Path) -> None:
        self.staging_root = staging_root
        self.state_path = staging_root / "recorder_state.json"
        self._producer_db: sqlite3.Connection | None = None

    def read_state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, payload: Mapping[str, Any]) -> None:
        write_json_atomic(self.state_path, payload)

    def open_producer_index(self) -> None:
        self._producer_db = sqlite3.connect(self.staging_root / "producer_ids.sqlite3")
        self._producer_db.execute("PRAGMA cache_size = -1024")
        self._producer_db.execute("PRAGMA temp_store = FILE")
        self._producer_db.execute(
            "CREATE TABLE producer_ids ("
            "episode_ordinal INTEGER NOT NULL, producer_frame_id TEXT NOT NULL, "
            "PRIMARY KEY (episode_ordinal, producer_frame_id)) WITHOUT ROWID"
        )
        self._producer_db.commit()

    def contains_producer_id(self, episode_ordinal: int, producer_id: str) -> bool:
        database = self._require_index()
        return (
            database.execute(
                "SELECT 1 FROM producer_ids "
                "WHERE episode_ordinal = ? AND producer_frame_id = ?",
                (episode_ordinal, producer_id),
            ).fetchone()
            is not None
        )

    def record_producer_id(self, episode_ordinal: int, producer_id: str) -> None:
        self._require_index().execute(
            "INSERT INTO producer_ids VALUES (?, ?)",
            (episode_ordinal, producer_id),
        )

    def close_producer_index(self) -> None:
        if self._producer_db is not None:
            self._producer_db.rollback()
            self._producer_db.close()
            self._producer_db = None

    def _require_index(self) -> sqlite3.Connection:
        if self._producer_db is None:
            raise RuntimeError("producer identity index is closed")
        return self._producer_db


__all__: list[str] = []
