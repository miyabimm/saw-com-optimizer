"""L-SHADE rolling checkpoint session over the shared checkpoint store."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from sawopt.io.checkpoints import CheckpointStore, LoadedCheckpoint
from sawopt.io.lifecycle import RunDisposition
from .lshade import validate_lshade_checkpoint_header


class LShadeCheckpointSession:
    """Use the shared rolling store for all managed L-SHADE checkpoints.

    The backend's existing JSON serializer and state payload remain canonical.
    """

    def __init__(
        self,
        stream_directory: str | Path,
        *,
        run_directory: str | Path,
        state_validator: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> None:
        self.store = CheckpointStore(stream_directory, run_directory=run_directory)
        self.state_validator = state_validator
        self.last_load: LoadedCheckpoint | None = None

    def _validate(self, backend: Any, state: Mapping[str, Any]) -> None:
        canonicalizer = backend.canonicalizer
        if (getattr(canonicalizer, "__self__", None) is backend
                and getattr(canonicalizer, "__name__", "") == "_default_canonicalizer"):
            canonicalizer = None
        probe = backend.__class__(
            backend.bounds.copy(),
            seed=0,
            config=copy.deepcopy(backend.config),
            integer_indices=backend.integer_indices,
            canonicalizer=canonicalizer,
            comparator=backend.comparator,
            source_config_fingerprint=backend.source_config_fingerprint,
        )
        probe.load_state_dict(state)
        if self.state_validator is not None:
            self.state_validator(state)

    @property
    def has_checkpoint(self) -> bool:
        return self.store.has_state

    @property
    def reference_metadata(self) -> dict[str, str]:
        """Return a durable artifact reference for the selected checkpoint mode.

        Managed runs refer to the logical rolling stream. Per-budget records
        are written before the next checkpoint save, so an existing latest
        file could already be stale for that record.
        """
        stream = self.store.directory
        if self.store.run_directory is not None:
            try:
                stream_reference = stream.relative_to(self.store.run_directory).as_posix()
            except ValueError:
                stream_reference = stream.as_posix()
        else:
            stream_reference = stream.as_posix()
        return {
            "checkpoint_policy": "rolling_latest_previous",
            "checkpoint_stream": stream_reference,
            "checkpoint_state": "runtime_recovery",
        }

    @property
    def reference_path(self) -> Path | None:
        """Return an existing physical checkpoint path, if one is available.

        Managed callers should use :attr:`reference_metadata` for durable
        result records. This property never points at a future final file.
        """
        if self.store.latest_path.is_file():
            return self.store.latest_path
        if self.store.previous_path.is_file():
            return self.store.previous_path
        return None

    def load(self, backend: Any) -> LoadedCheckpoint | None:
        include_final = False
        if self.store.run_directory is not None:
            marker = self.store.run_directory / "metadata" / "run_completion.json"
            if marker.is_file():
                try:
                    marker_value = json.loads(marker.read_text(encoding="utf-8"))
                    include_final = (
                        marker_value.get("disposition") == RunDisposition.COMPLETED.value
                        and marker_value.get("status") == RunDisposition.COMPLETED.value
                    )
                except (OSError, UnicodeError, ValueError):
                    include_final = False
        loaded = self.store.load_state(
            validator=lambda state: self._validate(backend, state),
            preflight_validator=validate_lshade_checkpoint_header,
            include_final=include_final,
        )
        backend.load_state_dict(loaded.state)
        self.last_load = loaded
        return loaded

    def save(self, backend: Any, *, extra_state: Mapping[str, Any] | None = None) -> Path:
        def writer(path: Path) -> None:
            state = backend.state_dict()
            if extra_state is not None:
                state["extra_state"] = copy.deepcopy(dict(extra_state))
            with Path(path).open("w", encoding="utf-8") as stream:
                json.dump(state, stream, indent=2, ensure_ascii=False, allow_nan=False)

        validator = lambda state: self._validate(backend, state)
        return self.store.write(writer, validator=validator)


__all__ = ["LShadeCheckpointSession"]
