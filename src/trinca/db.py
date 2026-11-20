"""Banco local SQLite: canais, vídeos, curiosidades, roteiros e publicações.

Todas as consultas usam parâmetros. Nomes de coluna em atualizações vêm
sempre de listas fixas definidas neste arquivo.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from .config import DEFAULT_SETTINGS
from .security import ValidationError

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    permission TEXT NOT NULL DEFAULT 'sem_autorizacao'
        CHECK (permission IN ('sem_autorizacao', 'autorizado')),
    permission_proof TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    youtube_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'novo' CHECK (status IN ('novo', 'analisado', 'erro'))
);
CREATE TABLE IF NOT EXISTS curiosities (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    start_s REAL NOT NULL CHECK (start_s >= 0),
    end_s REAL NOT NULL CHECK (end_s > start_s),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    scene_hint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'nova'
        CHECK (status IN ('nova', 'selecionada', 'descartada', 'usada'))
);
CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'em_roteiro'
        CHECK (status IN ('em_roteiro', 'aguardando_gravacao', 'gravado',
                          'aguardando_revisao', 'aprovado', 'rejeitado')),
    narration_mode TEXT NOT NULL DEFAULT 'propria'
        CHECK (narration_mode IN ('propria', 'sintetica')),
    narration_path TEXT NOT NULL DEFAULT '',
    render_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS script_blocks (
    id INTEGER PRIMARY KEY,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    curiosity_id INTEGER REFERENCES curiosities(id) ON DELETE SET NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    scene_hint TEXT NOT NULL DEFAULT '',
    media_path TEXT NOT NULL DEFAULT '',
    duration_s REAL NOT NULL DEFAULT 8 CHECK (duration_s > 0),
    trim_start REAL NOT NULL DEFAULT 0 CHECK (trim_start >= 0),
    trim_end REAL NOT NULL DEFAULT 8 CHECK (trim_end > trim_start)
);
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('youtube', 'instagram', 'tiktok')),
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'rascunho'
        CHECK (status IN ('rascunho', 'agendado', 'publicado', 'erro')),
    scheduled_at TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    package_path TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (script_id, platform)
);
CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL,
    last_searched_at TEXT NOT NULL DEFAULT ''
);
-- Vídeos de origem que já viraram publicação. O registro sobrevive à exclusão
-- do roteiro e do canal, para o mesmo vídeo nunca ser usado duas vezes.
CREATE TABLE IF NOT EXISTS used_videos (
    youtube_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    used_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT NOT NULL,
    service TEXT NOT NULL,
    units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, service)
);
"""

_SCRIPT_FIELDS = frozenset(
    {"title", "status", "narration_mode", "narration_path", "render_path", "original_audio"}
)
_BLOCK_FIELDS = frozenset(
    {"text", "caption", "media_path", "duration_s", "trim_start", "trim_end", "hook_text",
     "hotspot_s"}
)
_PUBLICATION_FIELDS = frozenset(
    {"title", "description", "hashtags", "status", "scheduled_at", "url", "package_path"}
)


# Um vídeo conta como usado quando algum roteiro usa uma curiosidade dele
# ou quando ele já foi publicado. Vale para consultas com a tabela videos como "v".
_VIDEO_USED = (
    "(EXISTS (SELECT 1 FROM script_blocks ub JOIN curiosities uq ON uq.id = ub.curiosity_id"
    " WHERE uq.video_id = v.id)"
    " OR EXISTS (SELECT 1 FROM used_videos uv WHERE uv.youtube_id = v.youtube_id))"
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repository:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            os.chmod(path, 0o600)
        with self._conn:
            self._conn.executescript(SCHEMA)
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        """Acrescenta as colunas criadas depois da primeira versão do banco."""
        additions = (
            ("channels", "uploads_playlist", "TEXT NOT NULL DEFAULT ''"),
            ("videos", "duration_s", "INTEGER NOT NULL DEFAULT 0"),
            ("channels", "monitored", "INTEGER NOT NULL DEFAULT 1"),
            ("videos", "theme", "TEXT NOT NULL DEFAULT ''"),
            ("scripts", "original_audio", "INTEGER NOT NULL DEFAULT 0"),
            ("curiosities", "hook_text", "TEXT NOT NULL DEFAULT ''"),
            ("curiosities", "hotspot_s", "REAL NOT NULL DEFAULT -1"),
            ("script_blocks", "hook_text", "TEXT NOT NULL DEFAULT ''"),
            ("script_blocks", "hotspot_s", "REAL NOT NULL DEFAULT -1"),
        )
        with self._conn:
            for table, column, definition in additions:
                existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            self._conn.execute("PRAGMA user_version = 4")

    def _update(self, table: str, allowed: frozenset[str], row_id: int, fields: dict) -> None:
        unknown = set(fields) - allowed
        if unknown or not fields:
            raise ValueError(f"Campos não permitidos: {sorted(unknown)}")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._conn:
            self._conn.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?", (*fields.values(), row_id)
            )

    # ----- canais -----

    def add_channel(self, youtube_id: str, name: str, uploads_playlist: str = "") -> int:
        """Acrescenta um canal monitorado pelo radar."""
        row = self._conn.execute(
            "SELECT id, monitored FROM channels WHERE youtube_id = ?", (youtube_id,)
        ).fetchone()
        with self._conn:
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO channels (youtube_id, name, uploads_playlist, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (youtube_id, name, uploads_playlist, _now()),
                )
                return int(cur.lastrowid)
            if row["monitored"]:
                raise ValidationError("Este canal já está na lista.")
            # O canal já existia por causa de um vídeo achado em busca por tema.
            self._conn.execute(
                "UPDATE channels SET monitored = 1, name = ?, uploads_playlist = ? WHERE id = ?",
                (name, uploads_playlist, row["id"]),
            )
        return int(row["id"])

    def ensure_channel(self, youtube_id: str, name: str) -> int:
        """Canal de um vídeo achado por tema: existe para o crédito, sem monitoramento."""
        row = self._conn.execute(
            "SELECT id FROM channels WHERE youtube_id = ?", (youtube_id,)
        ).fetchone()
        if row is not None:
            return int(row["id"])
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO channels (youtube_id, name, monitored, created_at)"
                " VALUES (?, ?, 0, ?)",
                (youtube_id, name, _now()),
            )
        return int(cur.lastrowid)

    def list_channels(self, monitored_only: bool = True) -> list[sqlite3.Row]:
        where = " WHERE monitored = 1" if monitored_only else ""
        return self._conn.execute(
            f"SELECT * FROM channels{where} ORDER BY name COLLATE NOCASE"
        ).fetchall()

    def set_channel_paused(self, channel_id: int, paused: bool) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE channels SET paused = ? WHERE id = ?", (int(paused), channel_id)
            )

    def set_channel_permission(self, channel_id: int, proof: str) -> None:
        """Registra que o canal autorizou o uso dos vídeos dele, com a prova (obrigatória)."""
        proof = proof.strip()
        if len(proof) < 10:
            raise ValidationError("Descreva a autorização (onde ela está) com pelo menos 10 letras.")
        with self._conn:
            self._conn.execute(
                "UPDATE channels SET permission = 'autorizado', permission_proof = ? WHERE id = ?",
                (proof[:500], channel_id),
            )

    def remove_channel(self, channel_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))

    # ----- temas -----

    def save_theme(self, query: str) -> int:
        """Guarda o tema e marca a data da busca. Devolve o id."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO themes (query, created_at, last_searched_at) VALUES (?, ?, ?)"
                " ON CONFLICT (query) DO UPDATE SET last_searched_at = excluded.last_searched_at",
                (query, _now(), _now()),
            )
        row = self._conn.execute("SELECT id FROM themes WHERE query = ?", (query,)).fetchone()
        return int(row["id"])

    def list_themes(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM themes ORDER BY last_searched_at DESC, id DESC"
        ).fetchall()

    def remove_theme(self, theme_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM themes WHERE id = ?", (theme_id,))

    # ----- vídeos -----

    def add_video(
        self, channel_id: int, youtube_id: str, title: str, published_at: str,
        duration_s: int = 0, theme: str = "",
    ) -> int | None:
        """Devolve o id do vídeo novo, ou None se ele já era conhecido ou já foi usado."""
        if self.is_video_used(youtube_id):
            return None
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO videos (channel_id, youtube_id, title, published_at,"
                " detected_at, duration_s, theme) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (channel_id, youtube_id, title, published_at, _now(), duration_s, theme),
            )
        return int(cur.lastrowid) if cur.rowcount else None

    def is_video_used(self, youtube_id: str) -> bool:
        """Verdadeiro se o vídeo já virou publicação (registro permanente)."""
        row = self._conn.execute(
            "SELECT 1 FROM used_videos WHERE youtube_id = ?", (youtube_id,)
        ).fetchone()
        return row is not None

    def list_videos(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._conn.execute(
            f"SELECT v.*, c.name AS channel_name, {_VIDEO_USED} AS used FROM videos v"
            " JOIN channels c ON c.id = v.channel_id"
            " ORDER BY v.published_at DESC, v.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def all_video_ids(self) -> set[str]:
        """Vídeos que a busca não deve trazer de novo: os conhecidos e os já usados."""
        rows = self._conn.execute(
            "SELECT youtube_id FROM videos UNION SELECT youtube_id FROM used_videos"
        ).fetchall()
        return {row["youtube_id"] for row in rows}

    def known_video_ids(self, channel_id: int) -> set[str]:
        rows = self._conn.execute(
            "SELECT youtube_id FROM videos WHERE channel_id = ?", (channel_id,)
        ).fetchall()
        return {row["youtube_id"] for row in rows}

    def set_video_status(self, video_id: int, status: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE videos SET status = ? WHERE id = ?", (status, video_id))

    # ----- curiosidades -----

    def add_curiosities(self, video_id: int, drafts: Iterable) -> int:
        rows = [
            (video_id, d.start_s, d.end_s, d.title, d.description, d.scene_hint,
             getattr(d, "hook_text", ""), getattr(d, "hotspot_s", -1.0))
            for d in drafts
        ]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO curiosities (video_id, start_s, end_s, title, description, scene_hint,"
                " hook_text, hotspot_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.execute("UPDATE videos SET status = 'analisado' WHERE id = ?", (video_id,))
        return len(rows)

    def list_curiosities(self, status: str | None = None) -> list[sqlite3.Row]:
        query = (
            "SELECT q.*, v.title AS video_title, v.youtube_id AS video_youtube_id,"
            f" v.theme AS theme, c.name AS channel_name, {_VIDEO_USED} AS video_used"
            " FROM curiosities q"
            " JOIN videos v ON v.id = q.video_id JOIN channels c ON c.id = v.channel_id"
        )
        params: tuple = ()
        if status is not None:
            query += " WHERE q.status = ?"
            params = (status,)
        query += " ORDER BY v.published_at DESC, v.id DESC, q.start_s"
        return self._conn.execute(query, params).fetchall()

    def set_curiosity_status(self, curiosity_ids: Sequence[int], status: str) -> None:
        with self._conn:
            self._conn.executemany(
                "UPDATE curiosities SET status = ? WHERE id = ?",
                [(status, cid) for cid in curiosity_ids],
            )

    # ----- roteiros -----

    def create_script(self, title: str, blocks: Sequence) -> int:
        """Cria o roteiro com seus blocos e marca as curiosidades como usadas.

        Cada vídeo de origem só pode ser usado uma vez: se alguma curiosidade vier
        de um vídeo que outro roteiro ou outra publicação já usou, nada é criado.
        """
        ids = [block.curiosity_id for block in blocks if block.curiosity_id is not None]
        if ids:
            marks = ", ".join("?" for _ in ids)
            taken = self._conn.execute(
                "SELECT DISTINCT v.title FROM curiosities q JOIN videos v ON v.id = q.video_id"
                f" WHERE q.id IN ({marks}) AND {_VIDEO_USED}",
                ids,
            ).fetchall()
            if taken:
                titles = "; ".join(row["title"] for row in taken)
                raise ValidationError(
                    f"Cada vídeo de origem só pode ser usado uma vez. Já usado: {titles}"
                )
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO scripts (title, created_at) VALUES (?, ?)", (title, _now())
            )
            script_id = int(cur.lastrowid)
            for position, block in enumerate(blocks, start=1):
                self._conn.execute(
                    "INSERT INTO script_blocks (script_id, curiosity_id, position, text, caption,"
                    " scene_hint, hook_text, hotspot_s)"
                    " SELECT ?, ?, ?, ?, ?, ?, COALESCE(q.hook_text, ''), COALESCE(q.hotspot_s, -1)"
                    " FROM (SELECT 1) LEFT JOIN curiosities q ON q.id = ?",
                    (script_id, block.curiosity_id, position, block.text, block.text,
                     block.scene_hint, block.curiosity_id),
                )
                if block.curiosity_id is not None:
                    self._conn.execute(
                        "UPDATE curiosities SET status = 'usada' WHERE id = ?",
                        (block.curiosity_id,),
                    )
        return script_id

    def list_scripts(self, statuses: Sequence[str] | None = None) -> list[sqlite3.Row]:
        if statuses:
            marks = ", ".join("?" for _ in statuses)
            return self._conn.execute(
                f"SELECT * FROM scripts WHERE status IN ({marks}) ORDER BY id DESC",
                tuple(statuses),
            ).fetchall()
        return self._conn.execute("SELECT * FROM scripts ORDER BY id DESC").fetchall()

    def get_script(self, script_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()

    def list_blocks(self, script_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT b.*, q.start_s AS source_start_s, q.end_s AS source_end_s,"
            " v.youtube_id AS video_youtube_id, c.id AS channel_id, c.name AS channel_name,"
            " c.permission AS channel_permission"
            " FROM script_blocks b"
            " LEFT JOIN curiosities q ON q.id = b.curiosity_id"
            " LEFT JOIN videos v ON v.id = q.video_id"
            " LEFT JOIN channels c ON c.id = v.channel_id"
            " WHERE b.script_id = ? ORDER BY b.position",
            (script_id,),
        ).fetchall()

    def update_script(self, script_id: int, **fields) -> None:
        self._update("scripts", _SCRIPT_FIELDS, script_id, fields)

    def update_block(self, block_id: int, **fields) -> None:
        self._update("script_blocks", _BLOCK_FIELDS, block_id, fields)

    def delete_script(self, script_id: int) -> None:
        """Apaga o roteiro e devolve suas curiosidades para o estado 'nova'."""
        with self._conn:
            self._conn.execute(
                "UPDATE curiosities SET status = 'nova' WHERE id IN"
                " (SELECT curiosity_id FROM script_blocks WHERE script_id = ?)",
                (script_id,),
            )
            self._conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))

    def script_sources(self, script_id: int) -> list[sqlite3.Row]:
        """Vídeos de origem das curiosidades do roteiro, para o crédito."""
        return self._conn.execute(
            "SELECT DISTINCT c.name AS channel_name, v.youtube_id AS video_youtube_id,"
            " v.title AS video_title FROM script_blocks b"
            " JOIN curiosities q ON q.id = b.curiosity_id"
            " JOIN videos v ON v.id = q.video_id JOIN channels c ON c.id = v.channel_id"
            " WHERE b.script_id = ? ORDER BY v.id",
            (script_id,),
        ).fetchall()

    # ----- publicações -----

    def upsert_publication(
        self, script_id: int, platform: str, title: str, description: str, hashtags: str
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO publications (script_id, platform, title, description, hashtags,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (script_id, platform) DO UPDATE SET title = excluded.title,"
                " description = excluded.description, hashtags = excluded.hashtags,"
                " updated_at = excluded.updated_at",
                (script_id, platform, title, description, hashtags, _now()),
            )

    def update_publication(self, publication_id: int, **fields) -> None:
        self._update("publications", _PUBLICATION_FIELDS, publication_id, fields)
        with self._conn:
            self._conn.execute(
                "UPDATE publications SET updated_at = ? WHERE id = ?", (_now(), publication_id)
            )
            if fields.get("status") in ("agendado", "publicado"):
                # A partir daqui os vídeos de origem ficam usados em definitivo.
                self._conn.execute(
                    "INSERT OR IGNORE INTO used_videos (youtube_id, title, used_at)"
                    " SELECT DISTINCT v.youtube_id, v.title, ? FROM publications p"
                    " JOIN script_blocks b ON b.script_id = p.script_id"
                    " JOIN curiosities q ON q.id = b.curiosity_id"
                    " JOIN videos v ON v.id = q.video_id WHERE p.id = ?",
                    (_now(), publication_id),
                )

    def list_publications(self, script_id: int | None = None) -> list[sqlite3.Row]:
        query = (
            "SELECT p.*, s.title AS script_title FROM publications p"
            " JOIN scripts s ON s.id = p.script_id"
        )
        params: tuple = ()
        if script_id is not None:
            query += " WHERE p.script_id = ?"
            params = (script_id,)
        query += " ORDER BY p.updated_at DESC, p.id DESC"
        return self._conn.execute(query, params).fetchall()

    # ----- configurações e cotas -----

    def get_setting(self, key: str) -> str:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS[key]

    def set_setting(self, key: str, value: str) -> None:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def add_usage(self, service: str, units: int = 1) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO api_usage (day, service, units) VALUES (?, ?, ?)"
                " ON CONFLICT (day, service) DO UPDATE SET units = units + excluded.units",
                (date.today().isoformat(), service, units),
            )

    def usage_today(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT service, units FROM api_usage WHERE day = ?", (date.today().isoformat(),)
        ).fetchall()
        return {row["service"]: row["units"] for row in rows}

    def pipeline_counts(self) -> dict[str, int]:
        def count(query: str) -> int:
            return int(self._conn.execute(query).fetchone()[0])

        return {
            "videos_novos": count("SELECT COUNT(*) FROM videos WHERE status = 'novo'"),
            "curiosidades_novas": count(
                "SELECT COUNT(*) FROM curiosities q JOIN videos v ON v.id = q.video_id"
                f" WHERE q.status = 'nova' AND NOT {_VIDEO_USED}"
            ),
            "aguardando_gravacao": count(
                "SELECT COUNT(*) FROM scripts WHERE status = 'aguardando_gravacao'"
            ),
            "aguardando_revisao": count(
                "SELECT COUNT(*) FROM scripts WHERE status = 'aguardando_revisao'"
            ),
            "publicados": count("SELECT COUNT(*) FROM publications WHERE status = 'publicado'"),
        }
