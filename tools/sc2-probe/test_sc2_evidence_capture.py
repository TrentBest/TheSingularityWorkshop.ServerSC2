import hashlib
import tempfile
import unittest
from pathlib import Path

from sc2_evidence_capture import (
    EvidenceError,
    persist_bounded_replay,
    validate_replay_info,
    validate_terminal_results,
)


class TerminalResultValidationTests(unittest.TestCase):
    def valid(self, **overrides):
        args = dict(
            status=5, ended_status=5,
            player_results=[{"player_id": 1, "result": 1}, {"player_id": 2, "result": 2}],
            expected_player_ids=[1, 2], undecided_result=0, accepted_results=[1, 2, 3],
        )
        args.update(overrides)
        return validate_terminal_results(**args)

    def test_accepts_exact_decisive_results(self):
        result = self.valid()
        self.assertTrue(result["passed"])
        self.assertEqual(result["participant_results"], [
            {"player_id": 1, "result": 1}, {"player_id": 2, "result": 2},
        ])

    def test_rejects_nonterminal_status(self):
        with self.assertRaisesRegex(EvidenceError, "Status.Ended") as caught:
            self.valid(status=3)
        self.assertEqual(caught.exception.code, "SC2_MATCH_NOT_ENDED")

    def test_rejects_duplicate_unknown_missing_and_undecided_results(self):
        cases = [
            ([{"player_id": 1, "result": 1}, {"player_id": 1, "result": 2}], "SC2_PLAYER_RESULT_DUPLICATE"),
            ([{"player_id": 1, "result": 1}, {"player_id": 9, "result": 2}], "SC2_PLAYER_RESULT_UNKNOWN"),
            ([{"player_id": 1, "result": 1}], "SC2_PLAYER_RESULT_MISSING"),
            ([{"player_id": 1, "result": 1}, {"player_id": 2, "result": 0}], "SC2_PLAYER_RESULT_NOT_DECISIVE"),
        ]
        for rows, code in cases:
            with self.subTest(code=code), self.assertRaises(EvidenceError) as caught:
                self.valid(player_results=rows)
            self.assertEqual(caught.exception.code, code)

    def test_rejects_duplicate_expected_ids(self):
        with self.assertRaises(EvidenceError) as caught:
            self.valid(expected_player_ids=[1, 1])
        self.assertEqual(caught.exception.code, "SC2_ASSIGNMENT_PLAYER_IDS_INVALID")


class ReplayPersistenceTests(unittest.TestCase):
    def test_persists_exact_bytes_and_digest(self):
        data = b"bounded replay fixture"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "match.SC2Replay"
            result = persist_bounded_replay(data, target, max_bytes=100, chunk_size=4)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(result["size_bytes"], len(data))

    def test_rejects_oversized_and_empty_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "match.SC2Replay"
            for data, limit, code in [(b"12345", 4, "SC2_REPLAY_TOO_LARGE"), (b"", 4, "SC2_REPLAY_EMPTY")]:
                with self.subTest(code=code), self.assertRaises(EvidenceError) as caught:
                    persist_bounded_replay(data, target, max_bytes=limit)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(target.exists())

    def test_cancellation_leaves_no_partial_or_destination(self):
        calls = iter([False, False, True])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "match.SC2Replay"
            with self.assertRaises(EvidenceError) as caught:
                persist_bounded_replay(b"abcdefgh", target, max_bytes=100, chunk_size=2,
                                       cancelled=lambda: next(calls))
            self.assertEqual(caught.exception.code, "SC2_REPLAY_CAPTURE_CANCELLED")
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


class ReplayInfoValidationTests(unittest.TestCase):
    def fixture(self):
        return {
            "map_name": "Abyssal Reef",
            "game_version": "5.0.17.12345",
            "player_results": [{"player_id": 1, "result": 1}, {"player_id": 2, "result": 2}],
        }

    def test_accepts_matching_replay_metadata(self):
        result = validate_replay_info(
            replay_info=self.fixture(), expected_map="Abyssal Reef",
            expected_game_version="5.0.17.12345", terminal_results={1: 1, 2: 2},
        )
        self.assertTrue(result["passed"])

    def test_rejects_map_version_and_result_contradictions(self):
        cases = [
            ({"map_name": "Other"}, "SC2_REPLAY_MAP_MISMATCH"),
            ({"game_version": "5.0.18"}, "SC2_REPLAY_GAME_VERSION_MISMATCH"),
            ({"player_results": [{"player_id": 1, "result": 1}]}, "SC2_REPLAY_RESULT_MISMATCH"),
        ]
        for change, code in cases:
            with self.subTest(code=code), self.assertRaises(EvidenceError) as caught:
                validate_replay_info(
                    replay_info={**self.fixture(), **change}, expected_map="Abyssal Reef",
                    expected_game_version="5.0.17.12345", terminal_results={1: 1, 2: 2},
                )
            self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
