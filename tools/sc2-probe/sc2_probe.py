#!/usr/bin/env python3
"""Opt-in SC2 process/API probe. This tool is isolated from the production host runtime."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProbeConfig:
    executable: Path
    install_dir: Path
    map_path: Path
    output_dir: Path
    expected_version: str
    base_port: int
    startup_timeout: float
    shutdown_timeout: float
    setup_sequence: bool = False
    observed_player_id: int | None = None
    player_races: dict[str, int] | None = None
    port_set: dict[str, Any] | None = None
    race_match: bool = False
    bot_race: int | None = None
    computer_race: int | None = None
    computer_difficulty: int | None = None
    computer_ai_build: int | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_config(config: ProbeConfig) -> list[str]:
    errors: list[str] = []
    if not config.executable.is_file():
        errors.append(f"SC2 executable does not exist: {config.executable}")
    if not config.install_dir.is_dir():
        errors.append(f"SC2 installation directory does not exist: {config.install_dir}")
    if not config.map_path.is_file():
        errors.append(f"Trusted map file does not exist: {config.map_path}")
    if not config.expected_version.strip():
        errors.append("Expected SC2 version/build is required")
    if not 1024 <= config.base_port <= 65532:
        errors.append("Base port must be between 1024 and 65532")
    if config.startup_timeout <= 0 or config.shutdown_timeout <= 0:
        errors.append("Startup and shutdown timeouts must be positive")
    if config.race_match:
        if not config.setup_sequence:
            errors.append("Race-match mode requires the opt-in setup sequence")
        if config.observed_player_id is None or not 0 <= config.observed_player_id <= 0xFFFFFFFF:
            errors.append("Race-match mode requires an explicit uint32 observed player ID")
        if config.bot_race is None:
            errors.append("Race-match mode requires an explicit bot race")
        if config.computer_race is None:
            errors.append("Race-match mode requires an explicit Computer race")
        if config.computer_difficulty is None:
            errors.append("Race-match mode requires an explicit Computer difficulty")
    elif config.setup_sequence:
        if config.observed_player_id is None or not 0 <= config.observed_player_id <= 0xFFFFFFFF:
            errors.append("Setup sequence requires an explicit uint32 observed player ID")
        if config.player_races is None or set(config.player_races) != {"player-1", "player-2"}:
            errors.append("Setup sequence requires explicit races for both players")
    if config.setup_sequence and config.port_set is None:
        errors.append("Setup sequence requires one explicit shared SC2 PortSet layout")
    if config.setup_sequence and config.port_set is not None:
        flattened: list[int] = []
        try:
            pairs = [config.port_set["server_ports"], *config.port_set.get("client_ports", ())]
            if any(len(pair) != 2 for pair in pairs):
                raise ValueError("PortSet pairs must contain exactly two ports")
            flattened.extend(port for pair in pairs for port in pair)
            if any(not 1 <= port <= 65535 for port in flattened):
                errors.append("Every explicit setup port must be between 1 and 65535")
            if len(flattened) != len(set(flattened)):
                errors.append("Ports in the shared SC2 PortSet layout must not overlap")
        except (KeyError, TypeError, ValueError):
            errors.append("Setup sequence requires valid explicit server/client PortSet pairs")
    listener_count = 2 if config.race_match else 3
    listener_ports = list(range(config.base_port, config.base_port + listener_count))
    if len(set(listener_ports)) != listener_count:
        errors.append("SC2 listener ports overlap")
    ports_to_check = list(listener_ports)
    if config.setup_sequence and config.port_set is not None:
        for pair in [config.port_set.get("server_ports", ()), *config.port_set.get("client_ports", ())]:
            ports_to_check.extend(pair)
        if set(listener_ports).intersection(ports_to_check[listener_count:]):
            errors.append("Explicit setup PortSet layout overlaps SC2 API listener ports")
    for port in dict.fromkeys(ports_to_check):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                errors.append(f"Required local port is already unavailable: {port}")
    return errors

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def exchange_protocol(
    connection: Any,
    request: Any,
    response: Any,
    expected_response_type: str,
    timeout: float,
) -> tuple[Any, dict[str, Any]]:
    """Send one SC2API request and capture its ordered protobuf exchange."""
    request_type = request.WhichOneof("request")
    if not request_type:
        raise RuntimeError("SC2API request has no selected request payload")
    request_bytes = request.SerializeToString()
    connection.settimeout(timeout)
    sent_utc = utc_now()
    connection.send_binary(request_bytes)
    response_bytes = connection.recv()
    received_utc = utc_now()
    response.ParseFromString(response_bytes)
    response_type = response.WhichOneof("response")
    request_id = request.id if request.HasField("id") else None
    response_id = response.id if response.HasField("id") else None
    event = {
        "transport": "websocket",
        "request_id": request_id,
        "response_id": response_id,
        "request_type": request_type,
        "response_type": response_type,
        "expected_response_type": expected_response_type,
        "response_type_matches": response_type == expected_response_type,
        "sent_utc": sent_utc,
        "received_utc": received_utc,
        "correlation": "SC2API responses are returned in request order; this exchange has one outstanding request",
        "request_protobuf_base64": base64.b64encode(request_bytes).decode("ascii"),
        "response_protobuf_base64": base64.b64encode(response_bytes).decode("ascii"),
    }
    # Return even mismatched exchanges so the caller can persist the raw
    # request/response evidence before failing the protocol gate.
    return response, event




def evaluate_setup_response(response: Any, expected_response_type: str) -> dict[str, Any]:
    """Fail closed on setup response errors and require a structured JoinGame acknowledgement."""
    response_type = response.WhichOneof("response")
    errors = list(getattr(response, "error", ()))
    payload = getattr(response, response_type) if response_type else None
    payload_error = None
    payload_error_name = None
    if payload is not None:
        field = payload.DESCRIPTOR.fields_by_name.get("error")
        if field is not None and payload.HasField("error"):
            payload_error = int(getattr(payload, "error"))
            enum_value = field.enum_type.values_by_number.get(payload_error)
            payload_error_name = enum_value.name if enum_value else None

    join_player_id = None
    join_acknowledged = response_type == "join_game"
    if join_acknowledged:
        join_player_id = (
            int(payload.player_id) if payload.HasField("player_id") else None
        )

    passed = (
        response_type == expected_response_type
        and not errors
        and payload_error is None
        and (not join_acknowledged or join_player_id is not None)
    )
    status = int(response.status) if response.HasField("status") else None
    return {
        "passed": passed,
        "response_type": response_type,
        "expected_response_type": expected_response_type,
        "envelope_errors": errors,
        "payload_error": payload_error,
        "payload_error_name": payload_error_name,
        "join_player_id": join_player_id,
        "status": status,
    }



def perform_setup_exchange(
    connection: Any,
    request: Any,
    response: Any,
    expected_response_type: str,
    timeout: float,
    *,
    role: str,
    gate_name: str,
    manifest: dict[str, Any],
    manifest_path: Path,
) -> tuple[Any, dict[str, Any]]:
    """Exchange one setup request, durably record evidence, then enforce its gate."""
    result, event = exchange_protocol(
        connection, request, response, expected_response_type, timeout
    )
    gate = evaluate_setup_response(result, expected_response_type)
    event["role"] = role
    event["setup_gate"] = gate
    manifest.setdefault("protocol_exchanges", []).append(event)
    manifest.setdefault("gates", {})[gate_name] = gate
    # Persist the raw exchange and evaluated gate before raising on failure.
    write_manifest(manifest_path, manifest)
    if not gate["passed"]:
        raise RuntimeError(
            f"{role} SC2API setup gate '{gate_name}' failed: "
            f"expected {expected_response_type}, received {gate['response_type']}"
        )
    return result, gate



def run_participant_hosted_setup_sequence(
    connections: dict[str, Any],
    sc2api_pb2: Any,
    *,
    map_path: str,
    observed_player_id: int,
    player_races: dict[str, int],
    port_set: dict[str, Any],
    timeout: float,
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Run the runner-contract candidate: player-1 (Participant A) creates and joins,
    player-2 (Participant B) joins independently, and the observer joins last."""
    player_roles = ("player-1", "player-2")
    role_labels = {"player-1": "participant-a", "player-2": "participant-b"}
    required_roles = {"observer", *player_roles}
    if set(connections) != required_roles:
        raise ValueError("Connections must contain exactly observer, player-1, and player-2")
    if set(player_races) != set(player_roles):
        raise ValueError("Explicit races are required for both participants")
    if "server_ports" not in port_set:
        raise ValueError("One explicit shared server PortSet is required")
    if timeout <= 0:
        raise ValueError("Setup exchange timeout must be positive")

    initial_exchange_count = len(manifest.get("protocol_exchanges", ()))
    steps = [
        {"ordinal": 1, "role": "participant-a", "request": "create_game"},
        {"ordinal": 2, "role": "participant-a", "request": "join_game", "participation": "race"},
        {"ordinal": 3, "role": "participant-b", "request": "join_game", "participation": "race"},
        {"ordinal": 4, "role": "observer", "request": "join_game", "participation": "observed_player_id"},
    ]
    manifest["setup_sequence"] = {
        "schema_version": 1,
        "strategy": "participant-hosted-1v1-with-independent-observer",
        "contract": "SingularityBot runner contract v1",
        "steps": steps,
        "inputs": {
            "map_path": map_path,
            "observed_player_id": observed_player_id,
            "player_races": dict(player_races),
            "shared_port_set_layout": {
                "server_ports": list(port_set["server_ports"]),
                "client_ports": [list(pair) for pair in port_set.get("client_ports", ())],
            },
        },
        "passed": False,
    }
    write_manifest(manifest_path, manifest)

    try:
        create_request = build_create_game_request(sc2api_pb2, map_path, 2)
        perform_setup_exchange(
            connections["player-1"], create_request, sc2api_pb2.Response(),
            "create_game", timeout, role="participant-a", gate_name="setup_create_game",
            manifest=manifest, manifest_path=manifest_path,
        )

        for role in player_roles:
            player_request = build_join_game_request(
                sc2api_pb2,
                race=player_races[role],
                server_ports=tuple(port_set["server_ports"]),
                client_ports=tuple(tuple(pair) for pair in port_set.get("client_ports", ())),
            )
            perform_setup_exchange(
                connections[role], player_request, sc2api_pb2.Response(),
                "join_game", timeout, role=role_labels[role], gate_name=f"setup_{role}_join",
                manifest=manifest, manifest_path=manifest_path,
            )

        observer_request = build_join_game_request(
            sc2api_pb2, observed_player_id=observed_player_id
        )
        perform_setup_exchange(
            connections["observer"], observer_request, sc2api_pb2.Response(),
            "join_game", timeout, role="observer", gate_name="setup_observer_join",
            manifest=manifest, manifest_path=manifest_path,
        )

        player_ids = {
            role_labels[role]: manifest["gates"][f"setup_{role}_join"]["join_player_id"]
            for role in player_roles
        }
        distinct_player_ids = player_ids["participant-a"] != player_ids["participant-b"]
        identity_gate = {
            "passed": distinct_player_ids,
            "player_ids": player_ids,
            "distinct_player_ids": distinct_player_ids,
            "requested_observed_player_id": observed_player_id,
            "observed_player_id_semantics_validated": False,
            "observer_join_acknowledged": manifest["gates"]["setup_observer_join"]["passed"],
        }
        manifest.setdefault("gates", {})["setup_player_identity"] = identity_gate
        write_manifest(manifest_path, manifest)
        if not identity_gate["passed"]:
            raise RuntimeError("SC2 player identity gate failed: duplicate player IDs")
    except Exception as exc:
        manifest["setup_sequence"]["error"] = str(exc)
        manifest["setup_sequence"]["exchange_count_at_failure"] = len(
            manifest.get("protocol_exchanges", ())
        ) - initial_exchange_count
        write_manifest(manifest_path, manifest)
        raise

    manifest["setup_sequence"]["passed"] = True
    manifest["setup_sequence"]["completed_utc"] = utc_now()
    write_manifest(manifest_path, manifest)
    return manifest["setup_sequence"]

def run_single_bot_computer_setup_sequence(
    connections: dict[str, Any],
    sc2api_pb2: Any,
    *,
    map_path: str,
    observed_player_id: int,
    bot_race: int,
    computer_race: int,
    computer_difficulty: int,
    computer_ai_build: int | None,
    port_set: dict[str, Any],
    timeout: float,
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Create one bot-vs-Computer match through a neutral observer process."""
    if set(connections) != {"observer", "player-1"}:
        raise ValueError("Connections must contain exactly observer and player-1")
    if "server_ports" not in port_set:
        raise ValueError("One explicit shared server PortSet is required")
    if timeout <= 0:
        raise ValueError("Setup exchange timeout must be positive")
    steps = [
        {"ordinal": 1, "role": "observer", "request": "create_game"},
        {"ordinal": 2, "role": "observer", "request": "join_game", "participation": "observed_player_id"},
        {"ordinal": 3, "role": "player-1", "request": "join_game", "participation": "race"},
    ]
    sequence = {
        "schema_version": 1,
        "strategy": "observer-hosted-single-participant-vs-computer-protocol-probe",
        "singularitybot_runner_launched": False,
        "player_join_client": "probe harness; not the SingularityBot runner",
        "steps": steps,
        "inputs": {
            "map_path": map_path,
            "observed_player_id": observed_player_id,
            "bot_race": bot_race,
            "computer_race": computer_race,
            "computer_difficulty": computer_difficulty,
            "computer_ai_build": computer_ai_build,
            "shared_port_set_layout": {
                "server_ports": list(port_set["server_ports"]),
                "client_ports": [list(pair) for pair in port_set.get("client_ports", ())],
            },
        },
        "passed": False,
    }
    manifest["setup_sequence"] = sequence
    write_manifest(manifest_path, manifest)
    initial_exchange_count = len(manifest.get("protocol_exchanges", ()))
    try:
        create_request = build_create_game_request(
            sc2api_pb2, map_path, 1,
            computer_races=(computer_race,),
            computer_difficulty=computer_difficulty,
            computer_ai_build=computer_ai_build,
        )
        perform_setup_exchange(
            connections["observer"], create_request, sc2api_pb2.Response(),
            "create_game", timeout, role="observer", gate_name="setup_create_game",
            manifest=manifest, manifest_path=manifest_path,
        )
        observer_request = build_join_game_request(
            sc2api_pb2, observed_player_id=observed_player_id,
        )
        perform_setup_exchange(
            connections["observer"], observer_request, sc2api_pb2.Response(),
            "join_game", timeout, role="observer", gate_name="setup_observer_join",
            manifest=manifest, manifest_path=manifest_path,
        )
        player_request = build_join_game_request(
            sc2api_pb2, race=bot_race,
            server_ports=tuple(port_set["server_ports"]),
            client_ports=tuple(tuple(pair) for pair in port_set.get("client_ports", ())),
        )
        perform_setup_exchange(
            connections["player-1"], player_request, sc2api_pb2.Response(),
            "join_game", timeout, role="player-1", gate_name="setup_bot_join",
            manifest=manifest, manifest_path=manifest_path,
        )
        bot_player_id = manifest["gates"]["setup_bot_join"]["join_player_id"]
        identity_gate = {
            "passed": bot_player_id is not None,
            "bot_player_id": bot_player_id,
            "computer_player_id": None,
            "computer_player_id_source": "pending_game_info_capture",
        }
        manifest.setdefault("gates", {})["setup_player_identity"] = identity_gate
        write_manifest(manifest_path, manifest)
        if not identity_gate["passed"]:
            raise RuntimeError("Bot JoinGame did not return a player ID")
    except Exception as exc:
        sequence["error"] = str(exc)
        sequence["exchange_count_at_failure"] = (
            len(manifest.get("protocol_exchanges", ())) - initial_exchange_count
        )
        write_manifest(manifest_path, manifest)
        raise
    sequence["passed"] = True
    sequence["completed_utc"] = utc_now()
    write_manifest(manifest_path, manifest)
    return sequence


def summarize_game_info(response: Any) -> dict[str, Any]:
    """Extract roster metadata without treating it as visibility evidence."""
    if not response.HasField("game_info"):
        raise ValueError("GameInfo response payload is missing")
    info = response.game_info
    players = []
    for player in info.player_info:
        item: dict[str, Any] = {}
        for field in ("player_id", "type", "race_requested", "race_actual", "player_name"):
            if player.HasField(field):
                item[field] = getattr(player, field)
        players.append(item)
    return {
        "map_name": info.map_name if info.HasField("map_name") else None,
        "player_info": players,
        "player_count": len(players),
    }


def summarize_observation(response: Any) -> dict[str, Any]:
    """Capture raw unit visibility metadata; this is not an isolation verdict."""
    if not response.HasField("observation"):
        raise ValueError("Observation response payload is missing")
    response_observation = response.observation
    if not response_observation.HasField("observation"):
        raise ValueError("Observation payload is missing its observation state")
    observation = response_observation.observation
    summary: dict[str, Any] = {
        "game_loop": observation.game_loop if observation.HasField("game_loop") else None,
        "raw_data_present": observation.HasField("raw_data"),
        "unit_count": 0,
        "units": [],
        "player_result_count": len(response_observation.player_result),
    }
    if observation.HasField("raw_data"):
        for unit in observation.raw_data.units:
            item: dict[str, Any] = {}
            for field in ("tag", "unit_type", "owner", "display_type", "alliance"):
                if unit.HasField(field):
                    item[field] = getattr(unit, field)
            summary["units"].append(item)
        summary["unit_count"] = len(summary["units"])
    return summary


def capture_post_join_observations(
    connections: dict[str, Any],
    sc2api_pb2: Any,
    *,
    timeout: float,
    manifest: dict[str, Any],
    manifest_path: Path,
    roles: tuple[str, ...] = ("observer", "player-1", "player-2"),
) -> dict[str, Any]:
    """Capture GameInfo and fog-respecting Observation snapshots from each role."""
    if not roles or set(connections) != set(roles):
        raise ValueError("Post-join capture roles must exactly match supplied connections")
    capture: dict[str, Any] = {
        "schema_version": 1,
        "disable_fog_requested": False,
        "roles": {},
        "information_isolation_validated": False,
        "passed": False,
    }
    manifest["post_join_capture"] = capture
    write_manifest(manifest_path, manifest)
    for role in roles:
        role_capture: dict[str, Any] = {"game_info": None, "observation": None}
        capture["roles"][role] = role_capture
        write_manifest(manifest_path, manifest)

        game_info_request = sc2api_pb2.Request()
        game_info_request.game_info.SetInParent()
        game_info_response, game_info_event = exchange_protocol(
            connections[role], game_info_request, sc2api_pb2.Response(),
            "game_info", timeout,
        )
        game_info_event["role"] = role
        game_info_event["gate"] = "post_join_game_info"
        manifest.setdefault("protocol_exchanges", []).append(game_info_event)
        game_info_gate = evaluate_setup_response(game_info_response, "game_info")
        role_capture["game_info"] = game_info_gate
        manifest.setdefault("gates", {})[f"{role}_game_info"] = game_info_gate
        write_manifest(manifest_path, manifest)
        if not game_info_gate["passed"]:
            raise RuntimeError(f"{role} GameInfo response gate failed")
        game_info_gate["summary"] = summarize_game_info(game_info_response)
        write_manifest(manifest_path, manifest)

        observation_request = sc2api_pb2.Request()
        observation_request.observation.disable_fog = False
        observation_response, observation_event = exchange_protocol(
            connections[role], observation_request, sc2api_pb2.Response(),
            "observation", timeout,
        )
        observation_event["role"] = role
        observation_event["gate"] = "post_join_observation"
        manifest.setdefault("protocol_exchanges", []).append(observation_event)
        observation_gate = evaluate_setup_response(observation_response, "observation")
        role_capture["observation"] = observation_gate
        manifest.setdefault("gates", {})[f"{role}_observation"] = observation_gate
        write_manifest(manifest_path, manifest)
        if not observation_gate["passed"]:
            raise RuntimeError(f"{role} Observation response gate failed")
        observation_summary = summarize_observation(observation_response)
        observation_gate["passed"] = observation_summary["raw_data_present"]
        observation_gate["summary"] = observation_summary
        write_manifest(manifest_path, manifest)
        if not observation_gate["passed"]:
            raise RuntimeError(f"{role} raw Observation response gate failed")

    capture["passed"] = True
    capture["information_isolation_validated"] = False
    capture["completed_utc"] = utc_now()
    write_manifest(manifest_path, manifest)
    return capture


def build_create_game_request(
    sc2api_pb2: Any,
    map_path: str,
    participant_count: int,
    random_seed: int | None = None,
    realtime: bool = False,
    computer_races: tuple[int, ...] = (),
    computer_difficulty: int | None = None,
    computer_ai_build: int | None = None,
) -> Any:
    """Build CreateGame for explicit human/bot participants and optional SC2 Computer opponents."""
    if not map_path or not map_path.strip():
        raise ValueError("A local map path is required")
    if participant_count < 1:
        raise ValueError("At least one participant is required")
    if computer_races and computer_difficulty is None:
        raise ValueError("Computer opponents require an explicit difficulty")
    request = sc2api_pb2.Request()
    create_game = request.create_game
    create_game.local_map.map_path = map_path
    for _ in range(participant_count):
        create_game.player_setup.add(type=sc2api_pb2.Participant)
    for race in computer_races:
        setup = create_game.player_setup.add(
            type=sc2api_pb2.Computer,
            race=race,
            difficulty=computer_difficulty,
        )
        if computer_ai_build is not None:
            setup.ai_build = computer_ai_build
    if random_seed is not None:
        if not 0 <= random_seed <= 0xFFFFFFFF:
            raise ValueError("Random seed must fit uint32")
        create_game.random_seed = random_seed
    create_game.realtime = realtime
    return request


def build_join_game_request(
    sc2api_pb2: Any,
    *,
    race: int | None = None,
    observed_player_id: int | None = None,
    server_ports: tuple[int, int] | None = None,
    client_ports: tuple[tuple[int, int], ...] = (),
    player_name: str | None = None,
    host_ip: str | None = None,
) -> Any:
    """Build a join request; port values are explicit inputs, never inferred."""
    if (race is None) == (observed_player_id is None):
        raise ValueError("Specify exactly one of race or observed_player_id")
    if observed_player_id is not None and not 0 <= observed_player_id <= 0xFFFFFFFF:
        raise ValueError("Observed player ID must fit uint32")

    port_pairs = ([server_ports] if server_ports is not None else []) + list(client_ports)
    flattened = [port for pair in port_pairs for port in pair]
    if any(not 1 <= port <= 65535 for port in flattened):
        raise ValueError("Every explicit port must be between 1 and 65535")
    if len(flattened) != len(set(flattened)):
        raise ValueError("Explicit join ports must not overlap")

    request = sc2api_pb2.Request()
    join_game = request.join_game
    if race is not None:
        join_game.race = race
    else:
        join_game.observed_player_id = observed_player_id
    join_game.options.raw = True
    if server_ports is not None:
        join_game.server_ports.game_port = server_ports[0]
        join_game.server_ports.base_port = server_ports[1]
    for game_port, base_port in client_ports:
        port_set = join_game.client_ports.add()
        port_set.game_port = game_port
        port_set.base_port = base_port
    if player_name is not None:
        join_game.player_name = player_name
    if host_ip is not None:
        join_game.host_ip = host_ip
    return request


def ping_process(
    port: int, timeout: float, log_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from s2clientprotocol import sc2api_pb2
        from websocket import create_connection
    except ImportError as exc:
        raise RuntimeError(
            "Probe dependencies are missing. Install tools/sc2-probe/requirements.txt."
        ) from exc

    connection = create_connection(
        f"ws://127.0.0.1:{port}/sc2api",
        timeout=timeout,
        enable_multithread=False,
    )
    try:
        request = sc2api_pb2.Request()
        request.ping.SetInParent()
        response, exchange = exchange_protocol(
            connection, request, sc2api_pb2.Response(), "ping", timeout
        )
        ping = response.ping
        result = {
            "game_version": ping.game_version,
            "data_version": ping.data_version,
            "data_build": ping.data_build,
            "base_build": ping.base_build,
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result, exchange
    finally:
        connection.close()


def evaluate_version_gate(protocol: dict[str, dict[str, Any]], expected_version: str) -> dict[str, Any]:
    fields = ("game_version", "data_version", "data_build", "base_build")
    fingerprints = {
        tuple(str(entry.get(field, "")) for field in fields)
        for entry in protocol.values()
    }
    observed = [
        {field: value for field, value in zip(fields, fingerprint)}
        for fingerprint in sorted(fingerprints)
    ]
    all_match = bool(protocol) and all(
        expected_version in str(entry.get("game_version", ""))
        for entry in protocol.values()
    )
    consistent = len(fingerprints) == 1 and all(
        all(str(entry.get(field, "")) for field in fields)
        for entry in protocol.values()
    )
    return {
        "passed": all_match and consistent,
        "expected_game_version": expected_version,
        "process_count": len(protocol),
        "all_processes_match_expected_game_version": all_match,
        "all_processes_report_same_complete_build": consistent,
        "observed_builds": observed,
    }


def run_probe(config: ProbeConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "probe": "server-sc2-race-match" if config.race_match else "server-sc2-three-process-bootstrap",
        "started_utc": utc_now(),
        "configuration": {
            "executable": str(config.executable),
            "install_dir": str(config.install_dir),
            "map_path": str(config.map_path),
            "expected_version": config.expected_version,
            "base_port": config.base_port,
            "setup_sequence_opt_in": config.setup_sequence,
            "race_match_opt_in": config.race_match,
            "bot_race": config.bot_race,
            "computer_race": config.computer_race,
            "computer_difficulty": config.computer_difficulty,
            "computer_ai_build": config.computer_ai_build,
            "observed_player_id": config.observed_player_id,
            "player_races": config.player_races,
            "shared_port_set_layout": config.port_set,
        },
        "map": {
            "path": str(config.map_path),
            "exists": config.map_path.is_file(),
            **(
                {"sha256": sha256_file(config.map_path), "size_bytes": config.map_path.stat().st_size}
                if config.map_path.is_file() else {}
            ),
        },
        "gates": {},
        "processes": [],
        "protocol": {},
        "protocol_exchanges": [],
        "cleanup": {"complete": False, "processes": []},
        "status": "failed",
    }
    errors = validate_config(config)
    if errors:
        manifest["gates"]["preflight"] = {"passed": False, "errors": errors}
        write_manifest(config.output_dir / "evidence.json", manifest)
        return 2
    manifest["gates"]["preflight"] = {"passed": True, "errors": []}

    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        process_roles = ("observer", "player-1") if config.race_match else ("observer", "player-1", "player-2")
        for ordinal, role in enumerate(process_roles):
            port = config.base_port + ordinal
            command = [
                str(config.executable),
                "-listen", "127.0.0.1",
                "-port", str(port),
                "-displayMode", "0",
            ]
            stdout_path = config.output_dir / f"{role}.stdout.log"
            stderr_path = config.output_dir / f"{role}.stderr.log"
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    command,
                    cwd=config.install_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
            processes.append((role, process))
            manifest["processes"].append({
                "role": role,
                "pid": process.pid,
                "listener_port": port,
                "command": command,
                "stdout_log": stdout_path.name,
                "stderr_log": stderr_path.name,
                "started_utc": utc_now(),
            })

        manifest["gates"]["process_launch"] = {"passed": True}
        for ordinal, (role, process) in enumerate(processes):
            port = config.base_port + ordinal
            deadline = time.monotonic() + config.startup_timeout
            last_error: str | None = None
            ping_result: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"{role} SC2 process exited early with code {process.returncode}")
                try:
                    ping_result, exchange = ping_process(
                        port, min(5.0, config.startup_timeout),
                        config.output_dir / f"{role}.ping.json",
                    )
                    manifest["protocol_exchanges"].append({
                        "role": role,
                        **exchange,
                    })
                    if not exchange["response_type_matches"]:
                        raise RuntimeError(
                            f"{role} SC2API returned response "
                            f"'{exchange['response_type']}' for request "
                            f"'{exchange['request_type']}'; expected "
                            f"'{exchange['expected_response_type']}'"
                        )
                    break
                except Exception as exc:  # bounded retry while SC2 initializes its listener
                    last_error = str(exc)
                    time.sleep(1.0)
            if ping_result is None:
                raise RuntimeError(f"{role} SC2 API did not become ping-ready: {last_error}")
            manifest["protocol"][role] = ping_result
            manifest["processes"][ordinal]["ping_ready_utc"] = utc_now()

        manifest["gates"]["api_ping"] = {"passed": True, "process_count": len(processes)}
        manifest["gates"]["version_match"] = evaluate_version_gate(
            manifest["protocol"], config.expected_version
        )
        if not manifest["gates"]["version_match"]["passed"]:
            raise RuntimeError(
                "SC2 processes do not all match the expected game version and identical complete build metadata"
            )

        if config.setup_sequence:
            from s2clientprotocol import sc2api_pb2
            from websocket import create_connection

            live_connections: dict[str, Any] = {}
            try:
                for ordinal, role in enumerate(process_roles):
                    live_connections[role] = create_connection(
                        f"ws://127.0.0.1:{config.base_port + ordinal}/sc2api",
                        timeout=min(10.0, config.startup_timeout),
                        enable_multithread=False,
                    )
                manifest["gates"]["setup_sequence"] = {"attempted": True, "passed": False}
                if config.race_match:
                    run_single_bot_computer_setup_sequence(
                        live_connections, sc2api_pb2,
                        map_path=str(config.map_path),
                        observed_player_id=config.observed_player_id,
                        bot_race=config.bot_race,
                        computer_race=config.computer_race,
                        computer_difficulty=config.computer_difficulty,
                        computer_ai_build=config.computer_ai_build,
                        port_set=config.port_set,
                        timeout=min(10.0, config.startup_timeout),
                        manifest=manifest,
                        manifest_path=config.output_dir / "evidence.json",
                    )
                else:
                    run_participant_hosted_setup_sequence(
                        live_connections, sc2api_pb2,
                        map_path=str(config.map_path),
                        observed_player_id=config.observed_player_id,
                        player_races=config.player_races,
                        port_set=config.port_set,
                        timeout=min(10.0, config.startup_timeout),
                        manifest=manifest,
                        manifest_path=config.output_dir / "evidence.json",
                    )
                manifest["gates"]["setup_sequence"] = {"attempted": True, "passed": True}
                capture_post_join_observations(
                    live_connections, sc2api_pb2,
                    timeout=min(10.0, config.startup_timeout),
                    manifest=manifest,
                    manifest_path=config.output_dir / "evidence.json",
                    roles=process_roles,
                )
                manifest["gates"]["post_join_capture"] = {"attempted": True, "passed": True}
                manifest["status"] = "live-race-match-setup-captured" if config.race_match else "live-post-join-capture-passed"
            finally:
                for connection in live_connections.values():
                    connection.close()
        else:
            manifest["gates"]["setup_sequence"] = {"attempted": False, "passed": False}
            manifest["status"] = "bootstrap-passed"
        return_code = 0
    except Exception as exc:
        manifest["error"] = str(exc)
        return_code = 1
    finally:
        for role, process in reversed(processes):
            outcome: dict[str, Any] = {"role": role, "pid": process.pid}
            if process.poll() is None:
                try:
                    if os.name == "nt":
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=config.shutdown_timeout)
                    outcome["terminated"] = True
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                check=False, capture_output=True, timeout=config.shutdown_timeout,
                            )
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=config.shutdown_timeout)
                        outcome["killed_after_timeout"] = True
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        outcome["terminated"] = False
                        outcome["error"] = str(exc)
            else:
                outcome["already_exited"] = True
            outcome["exit_code"] = process.poll()
            manifest["cleanup"]["processes"].append(outcome)
        manifest["cleanup"]["complete"] = all(
            item.get("terminated", item.get("already_exited", False))
            or item.get("killed_after_timeout", False)
            for item in manifest["cleanup"]["processes"]
        ) and len(manifest["cleanup"]["processes"]) == len(processes)
        manifest["finished_utc"] = utc_now()
        if not manifest["cleanup"]["complete"]:
            manifest["status"] = "failed"
            return_code = 1
        write_manifest(config.output_dir / "evidence.json", manifest)
    return return_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly launch three local SC2 processes")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--map", dest="map_path", type=Path)
    parser.add_argument("--expected-version")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--base-port", type=int, default=5000)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--shutdown-timeout", type=float, default=15.0)
    parser.add_argument("--setup-sequence", action="store_true", help="Opt in to live CreateGame/observer/player setup after bootstrap gates")
    parser.add_argument("--race-match", action="store_true", help="Opt in to a two-process observer-hosted bot-versus-Computer setup")
    parser.add_argument("--bot-race", type=int, help="Explicit SC2 race enum for the bot participant")
    parser.add_argument("--computer-race", type=int, help="Explicit SC2 race enum for the Computer opponent")
    parser.add_argument("--computer-difficulty", type=int, help="Explicit SC2 Computer difficulty enum")
    parser.add_argument("--computer-ai-build", type=int, help="Optional SC2 Computer AI build enum")
    parser.add_argument("--observed-player-id", "--observer-player-id", dest="observed_player_id", type=int, help="Player ID whose perspective the observer joins")
    parser.add_argument("--player-1-race", type=int)
    parser.add_argument("--player-2-race", type=int)
    parser.add_argument("--server-ports", help="Shared explicit game_port,base_port pair passed to both player joins")
    parser.add_argument("--client-ports", action="append", default=[], help="Shared explicit game_port,base_port pair; repeat for each client PortSet")
    return parser.parse_args(argv)


def parse_port_pair(value: str) -> tuple[int, int]:
    try:
        parts = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port pair must be two comma-separated integers") from exc
    if len(parts) != 2 or any(not 1 <= port <= 65535 for port in parts) or parts[0] == parts[1]:
        raise argparse.ArgumentTypeError("Port pair must contain two distinct ports in range 1..65535")
    return parts


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("No processes launched. Pass --execute and all trusted inputs to opt in.", file=sys.stderr)
        return 2
    required = {
        "--executable": args.executable,
        "--install-dir": args.install_dir,
        "--map": args.map_path,
        "--expected-version": args.expected_version,
        "--output-dir": args.output_dir,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        print("Missing required inputs: " + ", ".join(missing), file=sys.stderr)
        return 2
    setup_opt_in = args.setup_sequence or args.race_match
    if args.race_match:
        setup_required = {
            "--observed-player-id": args.observed_player_id,
            "--bot-race": args.bot_race,
            "--computer-race": args.computer_race,
            "--computer-difficulty": args.computer_difficulty,
            "--server-ports": args.server_ports,
        }
        if any(value is not None for value in (args.player_1_race, args.player_2_race)):
            print("--race-match cannot be combined with --player-1-race/--player-2-race.", file=sys.stderr)
            return 2
    elif args.setup_sequence:
        setup_required = {
            "--observed-player-id": args.observed_player_id,
            "--player-1-race": args.player_1_race,
            "--player-2-race": args.player_2_race,
            "--server-ports": args.server_ports,
        }
    else:
        setup_required = {}
    if setup_required:
        missing_setup = [name for name, value in setup_required.items() if value is None]
        if missing_setup:
            print("Setup mode requires: " + ", ".join(missing_setup), file=sys.stderr)
            return 2
        try:
            port_set = {"server_ports": parse_port_pair(args.server_ports), "client_ports": tuple(parse_port_pair(v) for v in args.client_ports)}
        except argparse.ArgumentTypeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        player_races = {"player-1": args.player_1_race, "player-2": args.player_2_race} if args.setup_sequence and not args.race_match else None
    else:
        extra = (args.observed_player_id, args.player_1_race, args.player_2_race, args.server_ports,
                 args.bot_race, args.computer_race, args.computer_difficulty, args.computer_ai_build)
        if any(value is not None for value in extra) or args.client_ports:
            print("Setup inputs require --setup-sequence or --race-match.", file=sys.stderr)
            return 2
        port_set = None
        player_races = None
    config = ProbeConfig(
        executable=args.executable.resolve(),
        install_dir=args.install_dir.resolve(),
        map_path=args.map_path.resolve(),
        output_dir=args.output_dir.resolve(),
        expected_version=args.expected_version,
        base_port=args.base_port,
        startup_timeout=args.startup_timeout,
        shutdown_timeout=args.shutdown_timeout,
        setup_sequence=setup_opt_in,
        race_match=args.race_match,
        bot_race=args.bot_race,
        computer_race=args.computer_race,
        computer_difficulty=args.computer_difficulty,
        computer_ai_build=args.computer_ai_build,
        observed_player_id=args.observed_player_id,
        player_races=player_races,
        port_set=port_set,
    )
    return run_probe(config)


if __name__ == "__main__":
    raise SystemExit(main())
