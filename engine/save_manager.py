"""Sauvegarde locale SQLite (SQLAlchemy 2.0).

Choix d'architecture : l'état complet d'une partie est sérialisé en JSON dans
une seule ligne, accompagné d'une version de schéma et d'une empreinte
SHA-256. La corruption (modification manuelle, écriture interrompue) est donc
détectée au chargement. Aucune donnée personnelle n'est stockée : ni nom de
joueur, ni identifiant machine, uniquement l'état de la simulation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

SCHEMA_VERSION = 1
AUTOSAVE_SLOT = "auto"


class SaveError(Exception):
    """Erreur générique de sauvegarde."""


class SaveNotFoundError(SaveError):
    pass


class SaveCorruptedError(SaveError):
    pass


class SaveVersionError(SaveError):
    pass


class Base(DeclarativeBase):
    pass


class SaveRecord(Base):
    __tablename__ = "saves"

    slot: Mapped[str] = mapped_column(String(32), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer)
    org_id: Mapped[str] = mapped_column(String(32))
    turn: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checksum: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)


class MetaRecord(Base):
    """Préférences et drapeaux (ex. tutoriel déjà vu). Clé/valeur JSON."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


@dataclass(frozen=True)
class SaveInfo:
    slot: str
    org_id: str
    turn: int
    label: str
    updated_at: datetime


def _checksum(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SaveManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self.db_path.as_posix()}", future=True)
        try:
            Base.metadata.create_all(self._engine)
        except DatabaseError as exc:
            raise SaveCorruptedError(f"Base de sauvegarde illisible : {exc}") from exc

    def close(self) -> None:
        self._engine.dispose()

    # -- parties -------------------------------------------------------------
    def save(self, state: dict[str, Any], slot: str = AUTOSAVE_SLOT, label: str = "") -> SaveInfo:
        payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        now = datetime.now(timezone.utc)
        record = SaveRecord(
            slot=slot,
            schema_version=SCHEMA_VERSION,
            org_id=str(state.get("org_id", "")),
            turn=int(state.get("turn", 0)),
            label=label[:120],
            updated_at=now,
            checksum=_checksum(payload),
            payload=payload,
        )
        with Session(self._engine) as session, session.begin():
            session.merge(record)
        return SaveInfo(slot, record.org_id, record.turn, record.label, now)

    def load(self, slot: str = AUTOSAVE_SLOT) -> dict[str, Any]:
        with Session(self._engine) as session:
            record = session.get(SaveRecord, slot)
            if record is None:
                raise SaveNotFoundError(f"Aucune sauvegarde « {slot} »")
            if record.schema_version != SCHEMA_VERSION:
                raise SaveVersionError(
                    f"Sauvegarde en version {record.schema_version}, attendu {SCHEMA_VERSION}"
                )
            if _checksum(record.payload) != record.checksum:
                raise SaveCorruptedError(f"Empreinte invalide pour « {slot} »")
            try:
                data = json.loads(record.payload)
            except json.JSONDecodeError as exc:
                raise SaveCorruptedError(f"JSON invalide pour « {slot} »") from exc
        if not isinstance(data, dict):
            raise SaveCorruptedError(f"Contenu inattendu pour « {slot} »")
        return data

    def exists(self, slot: str = AUTOSAVE_SLOT) -> bool:
        with Session(self._engine) as session:
            return session.get(SaveRecord, slot) is not None

    def delete(self, slot: str) -> bool:
        with Session(self._engine) as session, session.begin():
            record = session.get(SaveRecord, slot)
            if record is None:
                return False
            session.delete(record)
            return True

    def list_saves(self) -> list[SaveInfo]:
        with Session(self._engine) as session:
            rows = session.scalars(select(SaveRecord).order_by(SaveRecord.updated_at.desc()))
            return [SaveInfo(r.slot, r.org_id, r.turn, r.label, r.updated_at) for r in rows]

    def latest(self) -> SaveInfo | None:
        saves = self.list_saves()
        return saves[0] if saves else None

    # -- méta ------------------------------------------------------------------
    def get_meta(self, key: str, default: Any = None) -> Any:
        with Session(self._engine) as session:
            record = session.get(MetaRecord, key)
            if record is None:
                return default
            try:
                return json.loads(record.value)
            except json.JSONDecodeError:
                return default

    def set_meta(self, key: str, value: Any) -> None:
        with Session(self._engine) as session, session.begin():
            session.merge(MetaRecord(key=key, value=json.dumps(value, ensure_ascii=False)))
