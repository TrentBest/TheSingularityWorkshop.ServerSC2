import base64
import json
import tempfile
import unittest
from pathlib import Path

from sc2_probe import (
    ProbeConfig, build_create_game_request, build_join_game_request,
    exchange_protocol, evaluate_setup_response, evaluate_version_gate, perform_setup_exchange, parse_args, validate_config,
)



class FakeRequest:
    id = None

    def HasField(self, name):
        return name == "id" and self.id is not None

    def WhichOneof(self, name):
        return "ping" if name == "request" else None

    def SerializeToString(self):
        return b"request-ping"


class FakeResponse:
    def __init__(self):
        self.payload = None
        self.id = None

    def HasField(self, name):
        return name == "id" and self.id is not None

    def ParseFromString(self, payload):
        self.payload = json.loads(payload.decode("utf-8"))

    def WhichOneof(self, name):
        return self.payload.get("type") if name == "response" else None


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.timeout = None
        self.sent = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def send_binary(self, payload):
        self.sent = payload

    def recv(self):
        return self.response


class ProtocolTransportTests(unittest.TestCase):
    def test_exchange_records_types_timeout_timestamps_and_raw_protobuf(self):
        socket = FakeSocket(b'{"type":"ping"}')
        response, event = exchange_protocol(
            socket, FakeRequest(), FakeResponse(), "ping", 2.5
        )
        self.assertEqual(response.payload["type"], "ping")
        self.assertEqual(socket.timeout, 2.5)
        self.assertEqual(socket.sent, b"request-ping")
        self.assertEqual(event["request_type"], "ping")
        self.assertIsNone(event["request_id"])
        self.assertIsNone(event["response_id"])
        self.assertEqual(event["response_type"], "ping")
        self.assertTrue(event["response_type_matches"])
        self.assertEqual(
            base64.b64decode(event["request_protobuf_base64"]), b"request-ping"
        )
        self.assertTrue(event["sent_utc"])
        self.assertTrue(event["received_utc"])

    def test_exchange_captures_optional_envelope_ids_without_requiring_them(self):
        socket = FakeSocket(b'{"type":"ping"}')
        request = FakeRequest()
        request.id = 41
        response = FakeResponse()
        response.id = 41
        _, event = exchange_protocol(socket, request, response, "ping", 1.0)
        self.assertEqual(event["request_id"], 41)
        self.assertEqual(event["response_id"], 41)

    def test_exchange_preserves_unexpected_response_type_for_audit(self):
        socket = FakeSocket(b'{"type":"create_game"}')
        response, event = exchange_protocol(
            socket, FakeRequest(), FakeResponse(), "ping", 1.0
        )
        self.assertEqual(response.payload["type"], "create_game")
        self.assertEqual(event["response_type"], "create_game")
        self.assertEqual(event["expected_response_type"], "ping")
        self.assertFalse(event["response_type_matches"])
        self.assertEqual(
            base64.b64decode(event["response_protobuf_base64"]),
            b'{"type":"create_game"}',
        )


class DescriptorBackedRequestBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2clientprotocol import common_pb2, sc2api_pb2
        cls.protocol = sc2api_pb2
        cls.terran_race = common_pb2.Terran

    def test_create_game_uses_local_map_and_explicit_participant_count(self):
        request = build_create_game_request(
            self.protocol, "/trusted/maps/test.SC2Map", 2, random_seed=7
        )
        self.assertEqual(request.WhichOneof("request"), "create_game")
        self.assertEqual(request.create_game.local_map.map_path, "/trusted/maps/test.SC2Map")
        self.assertEqual(len(request.create_game.player_setup), 2)
        self.assertTrue(all(
            setup.type == self.protocol.Participant
            for setup in request.create_game.player_setup
        ))
        self.assertEqual(request.create_game.random_seed, 7)
        self.assertFalse(request.create_game.realtime)

    def test_join_player_and_observer_modes_use_distinct_oneof_fields(self):
        player = build_join_game_request(
            self.protocol, race=self.terran_race,
            server_ports=(5002, 5003), client_ports=((5004, 5005),),
        )
        observer = build_join_game_request(
            self.protocol, observed_player_id=0,
        )
        self.assertEqual(player.WhichOneof("request"), "join_game")
        self.assertEqual(player.join_game.WhichOneof("participation"), "race")
        self.assertEqual(player.join_game.race, self.terran_race)
        self.assertEqual(player.join_game.server_ports.game_port, 5002)
        self.assertEqual(
            [(p.game_port, p.base_port) for p in player.join_game.client_ports],
            [(5004, 5005)],
        )
        self.assertEqual(observer.join_game.WhichOneof("participation"), "observed_player_id")
        self.assertEqual(observer.join_game.observed_player_id, 0)
        self.assertFalse(observer.join_game.HasField("server_ports"))
        self.assertEqual(len(observer.join_game.client_ports), 0)

    def test_join_builder_rejects_ambiguous_participation_and_overlapping_ports(self):
        with self.assertRaises(ValueError):
            build_join_game_request(self.protocol)
        with self.assertRaises(ValueError):
            build_join_game_request(
                self.protocol, race=self.terran_race,
                server_ports=(5002, 5003), client_ports=((5003, 5004),),
            )

    def test_create_game_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            build_create_game_request(self.protocol, " ", 2)
        with self.assertRaises(ValueError):
            build_create_game_request(self.protocol, "map.SC2Map", 0)


class DescriptorBackedSetupResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2clientprotocol import sc2api_pb2
        cls.protocol = sc2api_pb2

    def test_create_game_response_rejects_payload_error(self):
        response = self.protocol.Response()
        response.create_game.error = self.protocol.ResponseCreateGame.MultiplayerUnsupported
        result = evaluate_setup_response(response, "create_game")
        self.assertFalse(result["passed"])
        self.assertEqual(result["payload_error_name"], "MultiplayerUnsupported")

    def test_join_game_requires_player_id_acknowledgement(self):
        response = self.protocol.Response()
        response.join_game.SetInParent()
        self.assertFalse(evaluate_setup_response(response, "join_game")["passed"])
        response.join_game.player_id = 2
        result = evaluate_setup_response(response, "join_game")
        self.assertTrue(result["passed"])
        self.assertEqual(result["join_player_id"], 2)

    def test_failed_setup_exchange_is_persisted_before_gate_raises(self):
        request = self.protocol.Request()
        request.create_game.SetInParent()
        response = self.protocol.Response()
        response.create_game.error = self.protocol.ResponseCreateGame.MultiplayerUnsupported
        response_bytes = response.SerializeToString()
        socket = FakeSocket(response_bytes)
        manifest = {"gates": {}, "protocol_exchanges": []}
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = Path(directory) / "evidence.json"
            with self.assertRaises(RuntimeError):
                perform_setup_exchange(
                    socket, request, self.protocol.Response(), "create_game", 1.0,
                    role="observer", gate_name="create_game",
                    manifest=manifest, manifest_path=evidence_path,
                )
            saved = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertFalse(saved["gates"]["create_game"]["passed"])
        self.assertEqual(len(saved["protocol_exchanges"]), 1)
        event = saved["protocol_exchanges"][0]
        self.assertEqual(event["role"], "observer")
        self.assertEqual(
            base64.b64decode(event["response_protobuf_base64"]), response_bytes
        )
        self.assertEqual(
            event["setup_gate"]["payload_error_name"], "MultiplayerUnsupported"
        )

    def test_envelope_errors_and_wrong_response_type_fail_closed(self):
        response = self.protocol.Response()
        response.create_game.SetInParent()
        response.error.append("setup warning/error reported by server")
        self.assertFalse(evaluate_setup_response(response, "create_game")["passed"])
        clean = self.protocol.Response()
        clean.ping.SetInParent()
        self.assertFalse(evaluate_setup_response(clean, "create_game")["passed"])



class ProbePreflightTests(unittest.TestCase):
    def test_execution_is_opt_in(self):
        args = parse_args([])
        self.assertFalse(args.execute)

    def test_missing_paths_fail_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ProbeConfig(
                executable=root / "missing.exe",
                install_dir=root / "missing-install",
                map_path=root / "missing-map.SC2Map",
                output_dir=root / "out",
                expected_version="5.0.17",
                base_port=5000,
                startup_timeout=30,
                shutdown_timeout=10,
            )
            errors = validate_config(config)
            self.assertTrue(any("SC2 executable" in error for error in errors))
            self.assertTrue(any("installation directory" in error for error in errors))
            self.assertTrue(any("Trusted map" in error for error in errors))

    def test_invalid_port_and_timeouts_fail_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "SC2.exe"
            install = root / "install"
            map_path = root / "map.SC2Map"
            executable.write_bytes(b"")
            install.mkdir()
            map_path.write_bytes(b"map")
            config = ProbeConfig(
                executable=executable,
                install_dir=install,
                map_path=map_path,
                output_dir=root / "out",
                expected_version="5.0.17",
                base_port=65533,
                startup_timeout=0,
                shutdown_timeout=-1,
            )
            errors = validate_config(config)
            self.assertTrue(any("Base port" in error for error in errors))
            self.assertTrue(any("timeouts" in error for error in errors))

    def test_version_gate_requires_all_processes_to_match_one_complete_build(self):
        protocol = {
            "observer": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-1": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-2": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
        }
        result = evaluate_version_gate(protocol, "5.0.17")
        self.assertTrue(result["passed"])
        self.assertTrue(result["all_processes_report_same_complete_build"])
        self.assertEqual(result["process_count"], 3)

    def test_version_gate_rejects_mixed_data_builds(self):
        protocol = {
            "observer": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-1": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-2": {
                "game_version": "5.0.17.12345",
                "data_version": "def",
                "data_build": 12346,
                "base_build": 12345,
            },
        }
        result = evaluate_version_gate(protocol, "5.0.17")
        self.assertFalse(result["passed"])
        self.assertTrue(result["all_processes_match_expected_game_version"])
        self.assertFalse(result["all_processes_report_same_complete_build"])

    def test_version_gate_rejects_incomplete_build_metadata(self):
        protocol = {
            "observer": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-1": {
                "game_version": "5.0.17.12345",
                "data_version": "abc",
                "data_build": 12345,
                "base_build": 12345,
            },
            "player-2": {
                "game_version": "5.0.17.12345",
                "data_version": "",
                "data_build": 12345,
                "base_build": 12345,
            },
        }
        result = evaluate_version_gate(protocol, "5.0.17")
        self.assertFalse(result["passed"])
        self.assertFalse(result["all_processes_report_same_complete_build"])


if __name__ == "__main__":
    unittest.main()
