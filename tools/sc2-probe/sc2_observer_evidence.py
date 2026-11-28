"""Strict protobuf adapters for independent-observer SC2 evidence.

Transport and process lifecycle stay in sc2_probe.py. These functions only
normalize actual SC2API Response envelopes into the existing evidence
validators; they never treat runner stdout as authoritative.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from sc2_evidence_capture import (
    EvidenceError,
    validate_replay_info,
    validate_terminal_results,
)


def extract_observer_terminal_results(
    response: Any,
    *,
    ended_status: int,
    expected_player_ids: Iterable[int],
    undecided_result: int,
    accepted_results: Iterable[int],
) -> dict[str, Any]:
    """Require an observer Observation response at Status.ended with decisive results."""
    response_type = response.WhichOneof("response")
    if response_type != "observation":
        raise EvidenceError(
            "SC2_OBSERVER_RESPONSE_TYPE_INVALID",
            f"Expected observation response, received {response_type!r}",
        )
    errors = list(getattr(response, "error", ()))
    if errors:
        raise EvidenceError(
            "SC2_OBSERVER_RESPONSE_ERROR",
            "Observer observation response contains SC2API errors",
        )
    if not response.HasField("status"):
        raise EvidenceError(
            "SC2_OBSERVER_STATUS_MISSING",
            "Observer response did not include the required SC2 lifecycle status",
        )
    if response.status != ended_status:
        raise EvidenceError(
            "SC2_MATCH_NOT_ENDED",
            "Observer has not reported Status.ended",
        )
    if not response.HasField("observation"):
        raise EvidenceError(
            "SC2_OBSERVER_OBSERVATION_MISSING",
            "Observer response has no observation payload",
        )

    normalized = []
    for item in response.observation.player_result:
        if not item.HasField("player_id") or not item.HasField("result"):
            raise EvidenceError(
                "SC2_PLAYER_RESULT_MALFORMED",
                "Observer terminal result is missing player_id or result",
            )
        normalized.append({
            "player_id": item.player_id,
            "result": item.result,
        })

    return validate_terminal_results(
        status=response.status,
        ended_status=ended_status,
        player_results=normalized,
        expected_player_ids=expected_player_ids,
        undecided_result=undecided_result,
        accepted_results=accepted_results,
    )


def extract_replay_info(
    response: Any,
    *,
    expected_map: str,
    expected_game_version: str,
    terminal_results: Mapping[int, int],
) -> dict[str, Any]:
    """Normalize ReplayInfo's nested PlayerInfoExtra records and cross-check results."""
    response_type = response.WhichOneof("response")
    if response_type != "replay_info":
        raise EvidenceError(
            "SC2_REPLAY_INFO_RESPONSE_TYPE_INVALID",
            f"Expected replay_info response, received {response_type!r}",
        )
    errors = list(getattr(response, "error", ()))
    if errors:
        raise EvidenceError(
            "SC2_REPLAY_INFO_RESPONSE_ERROR",
            "ReplayInfo response contains SC2API errors",
        )
    if not response.HasField("replay_info"):
        raise EvidenceError(
            "SC2_REPLAY_INFO_MISSING",
            "ReplayInfo response payload is missing",
        )

    info = response.replay_info
    if not info.HasField("map_name") or not info.HasField("game_version"):
        raise EvidenceError(
            "SC2_REPLAY_INFO_METADATA_MISSING",
            "ReplayInfo must include map_name and game_version",
        )

    results = []
    for extra in info.player_info:
        if not extra.HasField("player_info") or not extra.HasField("player_result"):
            raise EvidenceError(
                "SC2_REPLAY_RESULT_MALFORMED",
                "ReplayInfo player entry is missing player identity or result",
            )
        player = extra.player_info
        result = extra.player_result
        if not player.HasField("player_id") or not result.HasField("result"):
            raise EvidenceError(
                "SC2_REPLAY_RESULT_MALFORMED",
                "ReplayInfo player entry is missing player_id or result value",
            )
        results.append({
            "player_id": player.player_id,
            "result": result.result,
        })

    return validate_replay_info(
        replay_info={
            "map_name": info.map_name,
            "game_version": info.game_version,
            "player_results": results,
        },
        expected_map=expected_map,
        expected_game_version=expected_game_version,
        terminal_results=terminal_results,
    )
