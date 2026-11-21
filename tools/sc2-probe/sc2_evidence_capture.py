"""Fail-closed primitives for host-authoritative SC2 terminal/replay evidence.

This module deliberately does not own WebSocket transport, process lifecycle, or
match completion. Callers must obtain normalized values from the independent
observer connection and bind them to immutable host assignments.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class EvidenceError(RuntimeError):
    """Stable, machine-readable evidence failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_terminal_results(
    *,
    status: int,
    ended_status: int,
    player_results: Iterable[Mapping[str, Any]],
    expected_player_ids: Iterable[int],
    undecided_result: int,
    accepted_results: Iterable[int],
) -> dict[str, Any]:
    """Require Ended and exactly one decisive result for each assigned SC2 ID."""
    if status != ended_status:
        raise EvidenceError("SC2_MATCH_NOT_ENDED", "Observer has not reported Status.Ended")

    expected = tuple(expected_player_ids)
    if len(expected) < 2 or len(set(expected)) != len(expected):
        raise EvidenceError("SC2_ASSIGNMENT_PLAYER_IDS_INVALID", "Expected player IDs must be distinct and contain at least two participants")

    accepted = set(accepted_results)
    if undecided_result in accepted:
        raise ValueError("Undecided cannot be included in accepted_results")

    by_id: dict[int, int] = {}
    for item in player_results:
        try:
            player_id = int(item["player_id"])
            result = int(item["result"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("SC2_PLAYER_RESULT_MALFORMED", "A terminal player result is missing a valid player_id or result") from exc
        if player_id in by_id:
            raise EvidenceError("SC2_PLAYER_RESULT_DUPLICATE", f"Duplicate terminal result for SC2 player {player_id}")
        if player_id not in expected:
            raise EvidenceError("SC2_PLAYER_RESULT_UNKNOWN", f"Terminal result references unassigned SC2 player {player_id}")
        if result == undecided_result or result not in accepted:
            raise EvidenceError("SC2_PLAYER_RESULT_NOT_DECISIVE", f"SC2 player {player_id} has no accepted decisive result")
        by_id[player_id] = result

    missing = sorted(set(expected) - set(by_id))
    if missing:
        raise EvidenceError("SC2_PLAYER_RESULT_MISSING", f"Missing terminal results for SC2 players {missing}")
    return {
        "status": status,
        "participant_results": [
            {"player_id": player_id, "result": by_id[player_id]}
            for player_id in sorted(expected)
        ],
        "passed": True,
    }


def persist_bounded_replay(
    replay_bytes: bytes,
    destination: str | Path,
    *,
    max_bytes: int,
    cancelled: Callable[[], bool] | None = None,
    chunk_size: int = 1024 * 1024,
) -> dict[str, Any]:
    """Atomically persist bounded replay bytes and return their SHA-256 identity.

    A failed/cancelled write removes its temporary file and never leaves a
    partial destination. The caller remains responsible for artifact retention.
    """
    if not isinstance(replay_bytes, bytes) or not replay_bytes:
        raise EvidenceError("SC2_REPLAY_EMPTY", "Replay response did not contain non-empty bytes")
    if max_bytes <= 0 or chunk_size <= 0:
        raise ValueError("Replay size and chunk limits must be positive")
    if len(replay_bytes) > max_bytes:
        raise EvidenceError("SC2_REPLAY_TOO_LARGE", f"Replay is {len(replay_bytes)} bytes; limit is {max_bytes}")

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    digest = hashlib.sha256()
    written = 0
    try:
        if cancelled is not None and cancelled():
            raise EvidenceError("SC2_REPLAY_CAPTURE_CANCELLED", "Replay persistence was cancelled")
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".partial", dir=target.parent)
        with os.fdopen(fd, "wb") as stream:
            for offset in range(0, len(replay_bytes), chunk_size):
                if cancelled is not None and cancelled():
                    raise EvidenceError("SC2_REPLAY_CAPTURE_CANCELLED", "Replay persistence was cancelled")
                chunk = replay_bytes[offset:offset + chunk_size]
                count = stream.write(chunk)
                if count != len(chunk):
                    raise EvidenceError("SC2_REPLAY_PARTIAL_WRITE", "Replay artifact write was incomplete")
                digest.update(chunk)
                written += count
            stream.flush()
            os.fsync(stream.fileno())
        if written != len(replay_bytes):
            raise EvidenceError("SC2_REPLAY_PARTIAL_WRITE", "Persisted replay size does not match response size")
        if cancelled is not None and cancelled():
            raise EvidenceError("SC2_REPLAY_CAPTURE_CANCELLED", "Replay persistence was cancelled")
        os.replace(temporary, target)
        temporary = None
        return {
            "path": str(target),
            "size_bytes": written,
            "sha256": digest.hexdigest(),
            "passed": True,
        }
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def validate_replay_info(
    *,
    replay_info: Mapping[str, Any],
    expected_map: str,
    expected_game_version: str,
    terminal_results: Mapping[int, int],
) -> dict[str, Any]:
    """Cross-check normalized ReplayInfo against observer terminal evidence."""
    actual_map = replay_info.get("map_name")
    if not expected_map or actual_map != expected_map:
        raise EvidenceError("SC2_REPLAY_MAP_MISMATCH", "ReplayInfo map does not match the observed match map")

    actual_version = replay_info.get("game_version")
    if not expected_game_version or actual_version != expected_game_version:
        raise EvidenceError("SC2_REPLAY_GAME_VERSION_MISMATCH", "ReplayInfo game version does not match the observed SC2 build")

    raw_results = replay_info.get("player_results")
    if not isinstance(raw_results, (list, tuple)):
        raise EvidenceError("SC2_REPLAY_RESULTS_MISSING", "ReplayInfo has no player result collection")
    normalized: dict[int, int] = {}
    for item in raw_results:
        try:
            player_id, result = int(item["player_id"]), int(item["result"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("SC2_REPLAY_RESULT_MALFORMED", "ReplayInfo contains a malformed player result") from exc
        if player_id in normalized:
            raise EvidenceError("SC2_REPLAY_RESULT_DUPLICATE", f"ReplayInfo duplicates player {player_id}")
        normalized[player_id] = result

    expected = {int(key): int(value) for key, value in terminal_results.items()}
    if normalized != expected:
        raise EvidenceError("SC2_REPLAY_RESULT_MISMATCH", "ReplayInfo player results contradict observer terminal results")
    return {
        "map_name": actual_map,
        "game_version": actual_version,
        "player_results": [
            {"player_id": player_id, "result": normalized[player_id]}
            for player_id in sorted(normalized)
        ],
        "passed": True,
    }
