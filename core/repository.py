"""Async, atomic JSON persistence for Pigsty documents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from anyio import Lock
from anyio.to_thread import run_sync
from pydantic import ValidationError
from typing_extensions import override

from .models import PigstyDocument

if TYPE_CHECKING:
    from collections.abc import Callable

    from .identity import SessionIdentity


@dataclass(frozen=True, slots=True)
class PigstyDataError(Exception):
    """Raised when a persisted Pigsty file cannot be trusted."""

    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"invalid Pigsty data at {self.path}: {self.reason}"


class JsonPigstyRepository:
    """Persist one versioned Pigsty JSON document per session identity."""

    def __init__(self, data_dir: Path) -> None:
        """Create a repository rooted at the given data directory."""
        self._data_dir: Path = data_dir
        self._lock: Lock = Lock()

    @property
    def data_dir(self) -> Path:
        """Return the root directory assigned to this repository."""
        return self._data_dir

    def path_for(self, identity: SessionIdentity) -> Path:
        """Return the deterministic path for an identity without creating it."""
        return self._data_dir / identity.relative_path()

    async def document_paths(self) -> tuple[Path, ...]:
        """Return every persisted document path below the data directory."""
        return await run_sync(self._discover_document_paths)

    def _discover_document_paths(self) -> tuple[Path, ...]:
        if not self._data_dir.is_dir():
            return ()
        return tuple(sorted(self._data_dir.rglob("*.json")))

    async def load(self, identity: SessionIdentity) -> PigstyDocument:
        """Load one document, returning an unpersisted empty document when absent."""
        return await self._load_unlocked(identity)

    async def save(self, document: PigstyDocument) -> None:
        """Validate and atomically save one document."""
        validated = self._validate_document(document)
        identity = validated.to_identity()
        async with self._lock:
            await run_sync(
                self._atomic_write,
                self.path_for(identity),
                validated,
            )

    async def update(
        self,
        identity: SessionIdentity,
        mutation: Callable[[PigstyDocument], PigstyDocument],
    ) -> PigstyDocument:
        """Serialize one read-mutate-write operation for an identity."""
        path = self.path_for(identity)
        async with self._lock:
            current = await self._load_unlocked(identity)
            updated = self._validate_document(mutation(current), path)
            if updated.to_identity().relative_key != identity.relative_key:
                raise PigstyDataError(path, "mutation changed the document identity")
            await run_sync(self._atomic_write, path, updated)
            return updated

    async def update_path(
        self,
        path: Path,
        mutation: Callable[[PigstyDocument], PigstyDocument],
    ) -> PigstyDocument:
        """Serialize one read-mutate-write operation for a discovered file."""
        async with self._lock:
            current = await self._read_existing(path)
            updated = self._validate_document(mutation(current), path)
            if self.path_for(updated.to_identity()) != path:
                raise PigstyDataError(path, "mutation changed the document identity")
            await run_sync(self._atomic_write, path, updated)
            return updated

    async def _load_unlocked(self, identity: SessionIdentity) -> PigstyDocument:
        path = self.path_for(identity)
        try:
            return await self._read_existing(path)
        except FileNotFoundError:
            return PigstyDocument.empty_for_identity(identity)

    async def _read_existing(self, path: Path) -> PigstyDocument:
        """Read and validate one persisted document; missing files propagate."""
        try:
            document = await run_sync(self._read_document, path)
        except FileNotFoundError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
        ) as error:
            raise PigstyDataError(path, str(error)) from error

        if self.path_for(document.to_identity()) != path:
            raise PigstyDataError(path, "document identity does not match its path")
        return document

    @staticmethod
    def _read_document(path: Path) -> PigstyDocument:
        raw = path.read_text(encoding="utf-8")
        return PigstyDocument.model_validate_json(raw)

    @staticmethod
    def _validate_document(
        document: PigstyDocument,
        path: Path | None = None,
    ) -> PigstyDocument:
        target_path = Path("<memory>") if path is None else path
        try:
            return PigstyDocument.model_validate(document)
        except ValidationError as error:
            raise PigstyDataError(target_path, str(error)) from error

    @staticmethod
    def _atomic_write(path: Path, document: PigstyDocument) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                _ = temporary_file.write(document.model_dump_json(indent=2))
                _ = temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            _ = temporary_path.replace(path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
