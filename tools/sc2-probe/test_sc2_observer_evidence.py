"""Tests for strict observer protobuf evidence normalization."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from sc2_observer_evidence import (
    extract_observer_terminal_results,
    extract_replay_info,
)
from sc2_evidence_capture import EvidenceError


class ProtoMessage(SimpleNamespace):
    def HasField(self, name):
        return getattr(self, name, None) is not None

    def WhichOneof(self, _name):
        return self.response_type


def player_result(player_id, result):
    return ProtoMessage(player_id=player_id, result=result)


class ObserverEvidenceTests(unittest.TestCase):
    def observation_response(self, *, status=5, results=None, errors=()):
        payload = ProtoMessage(player_result=list(results or []))
        return ProtoMessage(
            response_type="observation",
            status=status,
            observation=payload,
            error=list(errors),
        )

    def test_extracts_only_ended_decisive_assigned_results(self):
        response = self.observation_response(
            results=[player_result(1, 1), player_result(2, 2)]
        )
        result = extract_observer_terminal_results(
            response,
            ended_status=5,
            expected_player_ids=[1, 2],
            undecided_result=0,
            accepted_results=[1, 2, 3],
        )
        self.assertTrue(result["passed"])
        self.assertEqual(
            result["participant_results"],
            [{"player_id": 1, "result": 1}, {"player_id": 2, "result": 2}],
        )

    def test_rejects_non_terminal_observer_status(self):
        with self.assertRaisesRegex(EvidenceError, "Status.ended"):
            extract_observer_terminal_results(
                self.observation_response(status=3, results=[]),
                ended_status=5,
                expected_player_ids=[1, 2],
                undecided_result=0,
                accepted_results=[1, 2, 3],
            )

    def test_rejects_runner_or_wrong_response_shape(self):
        response = self.observation_response()
        response.response_type = "join_game"
        with self.assertRaises(EvidenceError) as caught:
            extract_observer_terminal_results(
                response,
                ended_status=5,
                expected_player_ids=[1, 2],
                undecided_result=0,
                accepted_results=[1, 2, 3],
            )
        self.assertEqual(caught.exception.code, "SC2_OBSERVER_RESPONSE_TYPE_INVALID")

    def test_rejects_observer_response_errors(self):
        with self.assertRaises(EvidenceError) as caught:
            extract_observer_terminal_results(
                self.observation_response(errors=["bad request"]),
                ended_status=5,
                expected_player_ids=[1, 2],
                undecided_result=0,
                accepted_results=[1, 2, 3],
            )
        self.assertEqual(caught.exception.code, "SC2_OBSERVER_RESPONSE_ERROR")

    def test_normalizes_nested_replay_info_and_cross_checks_results(self):
        entries = [
            ProtoMessage(
                player_info=ProtoMessage(player_id=1),
                player_result=ProtoMessage(result=1),
            ),
            ProtoMessage(
                player_info=ProtoMessage(player_id=2),
                player_result=ProtoMessage(result=2),
            ),
        ]
        response = ProtoMessage(
            response_type="replay_info",
            error=[],
            replay_info=ProtoMessage(
                map_name="trusted-map",
                game_version="5.0.17",
                player_info=entries,
            ),
        )
        result = extract_replay_info(
            response,
            expected_map="trusted-map",
            expected_game_version="5.0.17",
            terminal_results={1: 1, 2: 2},
        )
        self.assertTrue(result["passed"])

    def test_rejects_replay_result_disagreement(self):
        entries = [
            ProtoMessage(
                player_info=ProtoMessage(player_id=1),
                player_result=ProtoMessage(result=2),
            ),
            ProtoMessage(
                player_info=ProtoMessage(player_id=2),
                player_result=ProtoMessage(result=1),
            ),
        ]
        response = ProtoMessage(
            response_type="replay_info",
            error=[],
            replay_info=ProtoMessage(
                map_name="trusted-map",
                game_version="5.0.17",
                player_info=entries,
            ),
        )
        with self.assertRaisesRegex(EvidenceError, "contradict"):
            extract_replay_info(
                response,
                expected_map="trusted-map",
                expected_game_version="5.0.17",
                terminal_results={1: 1, 2: 2},
            )


if __name__ == "__main__":
    unittest.main()
