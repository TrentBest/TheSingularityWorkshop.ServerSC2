import base64
import json
import tempfile
import unittest
from pathlib import Path

from sc2_probe import (
    ProbeConfig, build_create_game_request, build_join_game_request,
    exchange_protocol, evaluate_setup_response, evaluate_version_gate, perform_setup_exchange,
    run_observer_setup_sequence, run_single_bot_computer_setup_sequence,
    run_probe, capture_post_join_observations,
    parse_args, parse_port_pair, validate_config,
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


class QueuedFakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def send_binary(self, payload):
        self.sent.append(payload)

    def recv(self):
        return self.responses.pop(0)


class ObserverSetupSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2clientprotocol import common_pb2, sc2api_pb2
        cls.protocol = sc2api_pb2
        cls.terran = common_pb2.Terran
        cls.zerg = common_pb2.Zerg

    def response(self, payload_name, player_id=None, error=None):
        response = self.protocol.Response()
        payload = getattr(response, payload_name)
        if player_id is not None:
            payload.player_id = player_id
        if error is not None:
            payload.error = error
        else:
            payload.SetInParent()
        return response.SerializeToString()

    def setup_inputs(self):
        return {
            "observer": QueuedFakeSocket([
                self.response("create_game"),
                self.response("join_game", player_id=0),
            ]),
            "player-1": QueuedFakeSocket([self.response("join_game", player_id=1)]),
            "player-2": QueuedFakeSocket([self.response("join_game", player_id=2)]),
        }

    def port_set(self):
        return {"server_ports": (5002, 5003), "client_ports": ((5004, 5005),)}

    def test_candidate_sequence_records_explicit_inputs_and_orders_observer_first(self):
        connections = self.setup_inputs()
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            result = run_observer_setup_sequence(
                connections, self.protocol, map_path="trusted/test.SC2Map",
                observed_player_id=0,
                player_races={"player-1": self.terran, "player-2": self.zerg},
                port_set=self.port_set(), timeout=2.0,
                manifest=manifest, manifest_path=path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(result["passed"])
        self.assertEqual(
            [(event["role"], event["request_type"]) for event in saved["protocol_exchanges"]],
            [("observer", "create_game"), ("observer", "join_game"),
             ("player-1", "join_game"), ("player-2", "join_game")],
        )
        self.assertEqual(len(connections["observer"].sent), 2)
        self.assertEqual(len(connections["player-1"].sent), 1)
        self.assertEqual(len(connections["player-2"].sent), 1)
        create = self.protocol.Request.FromString(connections["observer"].sent[0])
        player_one = self.protocol.Request.FromString(connections["player-1"].sent[0])
        player_two = self.protocol.Request.FromString(connections["player-2"].sent[0])
        self.assertEqual(create.WhichOneof("request"), "create_game")
        self.assertNotEqual(connections["player-1"].sent[0], connections["observer"].sent[0])
        self.assertEqual(player_one.join_game.server_ports, player_two.join_game.server_ports)
        self.assertEqual(list(player_one.join_game.client_ports), list(player_two.join_game.client_ports))
        self.assertEqual(saved["setup_sequence"]["inputs"]["observed_player_id"], 0)
        self.assertEqual(saved["setup_sequence"]["inputs"]["shared_port_set_layout"]["server_ports"], [5002, 5003])

    def test_zero_observed_player_id_is_preserved_as_explicit_observer_input(self):
        connections = self.setup_inputs()
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            result = run_observer_setup_sequence(
                connections, self.protocol, map_path="trusted/test.SC2Map",
                observed_player_id=0,
                player_races={"player-1": self.terran, "player-2": self.zerg},
                port_set=self.port_set(), timeout=2.0,
                manifest=manifest, manifest_path=path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(result["passed"])
        self.assertEqual(saved["gates"]["setup_player_identity"]["requested_observed_player_id"], 0)
        self.assertFalse(saved["gates"]["setup_player_identity"]["observed_player_id_semantics_validated"])

    def test_duplicate_player_ids_fail_after_both_player_joins(self):
        connections = self.setup_inputs()
        connections["player-2"] = QueuedFakeSocket([self.response("join_game", player_id=1)])
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            with self.assertRaisesRegex(RuntimeError, "duplicate player IDs"):
                run_observer_setup_sequence(
                    connections, self.protocol, map_path="trusted/test.SC2Map",
                    observed_player_id=0,
                    player_races={"player-1": self.terran, "player-2": self.zerg},
                    port_set=self.port_set(), timeout=2.0,
                    manifest=manifest, manifest_path=path,
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(saved["gates"]["setup_player_identity"]["passed"])
        self.assertEqual(saved["gates"]["setup_player_identity"]["player_ids"], {"player-1": 1, "player-2": 1})
        self.assertFalse(saved["setup_sequence"]["passed"])

    def test_observer_join_failure_is_persisted_and_prevents_player_joins(self):
        connections = self.setup_inputs()
        failed_observer_join = self.protocol.Response()
        failed_observer_join.join_game.error = self.protocol.ResponseJoinGame.FeatureUnsupported
        connections["observer"] = QueuedFakeSocket([
            self.response("create_game"),
            failed_observer_join.SerializeToString(),
        ])
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            with self.assertRaises(RuntimeError):
                run_observer_setup_sequence(
                    connections, self.protocol, map_path="trusted/test.SC2Map",
                    observed_player_id=0,
                    player_races={"player-1": self.terran, "player-2": self.zerg},
                    port_set=self.port_set(), timeout=2.0,
                    manifest=manifest, manifest_path=path,
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(saved["setup_sequence"]["passed"])
        self.assertEqual(len(saved["protocol_exchanges"]), 2)
        self.assertEqual(saved["protocol_exchanges"][-1]["setup_gate"]["payload_error_name"], "FeatureUnsupported")
        self.assertEqual(connections["player-1"].sent, [])
        self.assertEqual(connections["player-2"].sent, [])


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

    def test_create_game_supports_one_participant_and_explicit_computer_race(self):
        from s2clientprotocol import common_pb2
        request = build_create_game_request(
            self.protocol,
            "/trusted/maps/test.SC2Map",
            1,
            computer_races=(common_pb2.Protoss,),
            computer_difficulty=self.protocol.Medium,
            computer_ai_build=self.protocol.Macro,
        )
        setups = request.create_game.player_setup
        self.assertEqual(len(setups), 2)
        self.assertEqual(setups[0].type, self.protocol.Participant)
        self.assertEqual(setups[1].type, self.protocol.Computer)
        self.assertEqual(setups[1].race, common_pb2.Protoss)
        self.assertEqual(setups[1].difficulty, self.protocol.Medium)
        self.assertEqual(setups[1].ai_build, self.protocol.Macro)

    def test_create_game_requires_explicit_computer_difficulty(self):
        from s2clientprotocol import common_pb2
        with self.assertRaisesRegex(ValueError, "explicit difficulty"):
            build_create_game_request(
                self.protocol,
                "/trusted/maps/test.SC2Map",
                1,
                computer_races=(common_pb2.Terran,),
            )

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
    def test_setup_sequence_is_separately_opt_in(self):
        self.assertFalse(parse_args([]).setup_sequence)
        self.assertTrue(parse_args(["--setup-sequence"]).setup_sequence)

    def test_explicit_port_pair_parser_rejects_ambiguous_or_invalid_values(self):
        self.assertEqual(parse_port_pair("5002, 5003"), (5002, 5003))
        for value in ("5002", "5002,5002", "0,5003", "5002,70000", "a,5003"):
            with self.subTest(value=value), self.assertRaises(Exception):
                parse_port_pair(value)

    def test_setup_sequence_preflight_requires_all_explicit_inputs_and_disjoint_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "SC2.exe"
            install = root / "install"
            map_path = root / "map.SC2Map"
            executable.write_bytes(b"")
            install.mkdir()
            map_path.write_bytes(b"map")
            base = dict(
                executable=executable, install_dir=install, map_path=map_path,
                output_dir=root / "out", expected_version="5.0.17", base_port=5000,
                startup_timeout=30, shutdown_timeout=10, setup_sequence=True,
            )
            missing = validate_config(ProbeConfig(**base))
            self.assertTrue(any("observed player ID" in error for error in missing))
            valid = dict(
                **base, observed_player_id=0,
                player_races={"player-1": 1, "player-2": 2},
                port_set={"server_ports": (5100, 5101), "client_ports": ((5102, 5103), (5104, 5105))},
            )
            self.assertFalse(validate_config(ProbeConfig(**valid)))
            valid["port_set"]["client_ports"] = ((5101, 5103),)
            self.assertTrue(any("overlap" in error for error in validate_config(ProbeConfig(**valid))))

    def test_execution_is_opt_in(self):
        args = parse_args([])
        self.assertFalse(args.execute)

    def test_run_probe_records_missing_map_preflight_without_hashing_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            config = ProbeConfig(
                executable=root / "missing.exe",
                install_dir=root / "missing-install",
                map_path=root / "missing-map.SC2Map",
                output_dir=output,
                expected_version="5.0.17",
                base_port=5000,
                startup_timeout=30,
                shutdown_timeout=10,
            )
            self.assertEqual(run_probe(config), 2)
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            self.assertFalse(evidence["map"]["exists"])
            self.assertNotIn("sha256", evidence["map"])
            self.assertFalse(evidence["gates"]["preflight"]["passed"])

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


class SingleBotComputerSetupSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2clientprotocol import common_pb2, sc2api_pb2
        cls.protocol = sc2api_pb2
        cls.terran = common_pb2.Terran
        cls.zerg = common_pb2.Zerg

    def response(self, kind, player_id=None, error=None):
        response = self.protocol.Response()
        payload = getattr(response, kind)
        if player_id is not None:
            payload.player_id = player_id
        if error is not None:
            payload.error = error
        return response.SerializeToString()

    def test_observer_creates_one_bot_one_computer_and_bot_joins(self):
        observer = QueuedFakeSocket([
            self.response("create_game"),
            self.response("join_game", player_id=0),
        ])
        bot = QueuedFakeSocket([self.response("join_game", player_id=1)])
        manifest = {"gates": {}, "protocol_exchanges": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            result = run_single_bot_computer_setup_sequence(
                {"observer": observer, "player-1": bot}, self.protocol,
                map_path="/trusted/maps/test.SC2Map",
                observed_player_id=0,
                bot_race=self.terran,
                computer_race=self.zerg,
                computer_difficulty=self.protocol.Medium,
                computer_ai_build=self.protocol.Macro,
                port_set={"server_ports": (5100, 5101), "client_ports": ((5102, 5103),)},
                timeout=2.0, manifest=manifest, manifest_path=path,
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["strategy"], "observer-hosted-single-bot-vs-computer")
            create = self.protocol.Request()
            create.ParseFromString(observer.sent[0])
            setups = create.create_game.player_setup
            self.assertEqual(len(setups), 2)
            self.assertEqual([item.type for item in setups], [self.protocol.Participant, self.protocol.Computer])
            self.assertEqual(setups[1].race, self.zerg)
            self.assertEqual(setups[1].difficulty, self.protocol.Medium)
            join = self.protocol.Request()
            join.ParseFromString(bot.sent[0])
            self.assertEqual(join.join_game.race, self.terran)
            self.assertEqual(join.join_game.server_ports.game_port, 5100)
            self.assertTrue(manifest["gates"]["setup_player_identity"]["passed"])
            self.assertEqual(len(manifest["protocol_exchanges"]), 3)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["setup_sequence"]["passed"])

    def test_computer_setup_failure_is_persisted_before_raise(self):
        observer = QueuedFakeSocket([
            self.response(
                "create_game",
                error=self.protocol.ResponseCreateGame.MultiplayerUnsupported,
            ),
        ])
        bot = QueuedFakeSocket([])
        manifest = {"gates": {}, "protocol_exchanges": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            with self.assertRaisesRegex(RuntimeError, "setup_create_game"):
                run_single_bot_computer_setup_sequence(
                    {"observer": observer, "player-1": bot}, self.protocol,
                    map_path="/trusted/maps/test.SC2Map",
                    observed_player_id=0,
                    bot_race=self.terran,
                    computer_race=self.zerg,
                    computer_difficulty=self.protocol.Medium,
                    computer_ai_build=None,
                    port_set={"server_ports": (5100, 5101)},
                    timeout=2.0, manifest=manifest, manifest_path=path,
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(saved["gates"]["setup_create_game"]["passed"])
            self.assertEqual(len(saved["protocol_exchanges"]), 1)
            self.assertEqual(len(bot.sent), 0)



class PostJoinObservationCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from s2clientprotocol import sc2api_pb2
        cls.protocol = sc2api_pb2

    def response_bytes(self, role, payload):
        response = self.protocol.Response()
        if payload == "game_info":
            info = response.game_info
            info.map_name = "ProbeMap"
            player = info.player_info.add()
            player.player_id = 1
            player.type = self.protocol.Participant
        else:
            observation = response.observation.observation
            observation.game_loop = 0
            observation.raw_data.SetInParent()
            unit = observation.raw_data.units.add()
            unit.tag = 123
            unit.unit_type = 45
            unit.owner = 1
            unit.display_type = 1
            unit.alliance = 1
        return response.SerializeToString()

    def test_captures_game_info_and_fog_respecting_raw_observations(self):
        connections = {
            role: QueuedFakeSocket([
                self.response_bytes(role, "game_info"),
                self.response_bytes(role, "observation"),
            ])
            for role in ("observer", "player-1", "player-2")
        }
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            result = capture_post_join_observations(
                connections, self.protocol, timeout=2.0,
                manifest=manifest, manifest_path=path,
            )
            self.assertTrue(result["passed"])
            self.assertFalse(result["disable_fog_requested"])
            self.assertFalse(result["information_isolation_validated"])
            self.assertEqual(len(manifest["protocol_exchanges"]), 6)
            for role in ("observer", "player-1", "player-2"):
                self.assertEqual(result["roles"][role]["game_info"]["summary"]["map_name"], "ProbeMap")
                self.assertEqual(result["roles"][role]["observation"]["summary"]["unit_count"], 1)
                request = self.protocol.Request()
                request.ParseFromString(connections[role].sent[1])
                self.assertFalse(request.observation.disable_fog)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(persisted["post_join_capture"]["passed"])
            self.assertEqual(persisted["post_join_capture"]["roles"]["observer"]["observation"]["summary"]["units"][0]["tag"], 123)

    def test_rejects_observation_without_raw_data(self):
        connections = {}
        for role in ("observer", "player-1", "player-2"):
            info = self.protocol.Response()
            info.game_info.map_name = "ProbeMap"
            observation = self.protocol.Response()
            observation.observation.observation.game_loop = 0
            connections[role] = QueuedFakeSocket([
                info.SerializeToString(), observation.SerializeToString(),
            ])
        manifest = {"protocol_exchanges": [], "gates": {}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "raw Observation"):
                capture_post_join_observations(
                    connections, self.protocol, timeout=2.0,
                    manifest=manifest, manifest_path=Path(directory) / "evidence.json",
                )
            self.assertFalse(manifest["gates"]["observer_observation"]["passed"])
            self.assertEqual(len(manifest["protocol_exchanges"]), 2)



if __name__ == "__main__":
    unittest.main()
