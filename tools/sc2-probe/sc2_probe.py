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
    observer_player_id: int | None = None
    player_races: dict[str, int] | None = None
    player_port_sets: dict[str, dict[str, Any]] | None = None


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
    if config.setup_sequence:
        if config.observer_player_id is None or not 0 <= config.observer_player_id <= 0xFFFFFFFF:
            errors.append("Setup sequence requires an explicit uint32 observer player ID")
        if config.player_races is None or set(config.player_races) != {"player-1", "player-2"}:
            errors.append("Setup sequence requires explicit races for both players")
        if config.player_port_sets is None or set(config.player_port_sets) != {"player-1", "player-2"}:
            errors.append("Setup sequence requires explicit PortSets for both players")
        elif config.player_port_sets is not None:
            flattened: list[int] = []
            try:
                for role in ("player-1", "player-2"):
                    ports = config.player_port_sets[role]
                    pairs = [ports["server_ports"], *ports.get("client_ports", ())]
                    if any(len(pair) != 2 for pair in pairs):
                        raise ValueError("PortSet pairs must contain exactly two ports")
                    flattened.extend(port for pair in pairs for port in pair)
                if any(not 1 <= port <= 65535 for port in flattened):
                    errors.append("Every explicit setup port must be between 1 and 65535")
                if len(flattened) != len(set(flattened)):
                    errors.append("Explicit setup PortSets overlap across players or within a player")
            except (KeyError, TypeError, ValueError):
                errors.append("Setup sequence requires valid explicit server/client PortSet pairs")
    ports = range(config.base_port, config.base_port + 3)
    if len(set(ports)) != 3:
        errors.append("SC2 listener ports overlap")
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                errors.append(f"Listener port is already unavailable: {port}")
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



def run_observer_setup_sequence(
    connections: dict[str, Any],
    sc2api_pb2: Any,
    *,
    map_path: str,
    observer_player_id: int,
    player_races: dict[str, int],
    player_port_sets: dict[str, dict[str, Any]],
    timeout: float,
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Run the candidate observer-hosted 1v1 setup using only explicit inputs.

    The observer is the sole CreateGame caller. No port layout or observer
    identity is inferred here; both are supplied by the caller and recorded.
    This is a probe sequence, not evidence that a particular SC2 build supports it.
    """
    player_roles = ("player-1", "player-2")
    required_roles = {"observer", *player_roles}
    if set(connections) != required_roles:
        raise ValueError("Connections must contain exactly observer, player-1, and player-2")
    if set(player_races) != set(player_roles):
        raise ValueError("Explicit player races are required for player-1 and player-2")
    if set(player_port_sets) != set(player_roles):
        raise ValueError("Explicit port sets are required for player-1 and player-2")
    if timeout <= 0:
        raise ValueError("Setup exchange timeout must be positive")

    initial_exchange_count = len(manifest.get("protocol_exchanges", ()))
    steps = [
        {"ordinal": 1, "role": "observer", "request": "create_game"},
        {"ordinal": 2, "role": "observer", "request": "join_game", "participation": "observed_player_id"},
        *[
            {"ordinal": ordinal + 3, "role": role, "request": "join_game", "participation": "race"}
            for ordinal, role in enumerate(player_roles)
        ],
    ]
    manifest["setup_sequence"] = {
        "schema_version": 1,
        "strategy": "candidate-observer-hosted-1v1",
        "steps": steps,
        "inputs": {
            "map_path": map_path,
            "observer_player_id": observer_player_id,
            "player_races": dict(player_races),
            "player_port_sets": {
                role: {
                    "server_ports": list(player_port_sets[role]["server_ports"]),
                    "client_ports": [
                        list(pair) for pair in player_port_sets[role].get("client_ports", ())
                    ],
                }
                for role in player_roles
            },
        },
        "passed": False,
    }
    write_manifest(manifest_path, manifest)

    try:
        create_request = build_create_game_request(sc2api_pb2, map_path, 2)
        perform_setup_exchange(
            connections["observer"], create_request, sc2api_pb2.Response(),
            "create_game", timeout, role="observer", gate_name="setup_create_game",
            manifest=manifest, manifest_path=manifest_path,
        )

        observer_request = build_join_game_request(
            sc2api_pb2, observed_player_id=observer_player_id
        )
        perform_setup_exchange(
            connections["observer"], observer_request, sc2api_pb2.Response(),
            "join_game", timeout, role="observer", gate_name="setup_observer_join",
            manifest=manifest, manifest_path=manifest_path,
        )

        for role in player_roles:
            ports = player_port_sets[role]
            player_request = build_join_game_request(
                sc2api_pb2,
                race=player_races[role],
                server_ports=tuple(ports["server_ports"]),
                client_ports=tuple(tuple(pair) for pair in ports.get("client_ports", ())),
            )
            perform_setup_exchange(
                connections[role], player_request, sc2api_pb2.Response(),
                "join_game", timeout, role=role, gate_name=f"setup_{role}_join",
                manifest=manifest, manifest_path=manifest_path,
            )
    except Exception as exc:
        manifest["setup_sequence"]["error"] = str(exc)
        manifest["setup_sequence"]["failed_step_count"] = len(
            manifest.get("protocol_exchanges", ())
        ) - initial_exchange_count
        write_manifest(manifest_path, manifest)
        raise

    manifest["setup_sequence"]["passed"] = True
    manifest["setup_sequence"]["completed_utc"] = utc_now()
    write_manifest(manifest_path, manifest)
    return manifest["setup_sequence"]


def build_create_game_request(
    sc2api_pb2: Any,
    map_path: str,
    participant_count: int,
    random_seed: int | None = None,
    realtime: bool = False,
) -> Any:
    """Build CreateGame only from fields present in the pinned SC2API schema."""
    if not map_path or not map_path.strip():
        raise ValueError("A local map path is required")
    if participant_count < 1:
        raise ValueError("At least one participant is required")
    request = sc2api_pb2.Request()
    create_game = request.create_game
    create_game.local_map.map_path = map_path
    for _ in range(participant_count):
        create_game.player_setup.add(type=sc2api_pb2.Participant)
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
        "probe": "server-sc2-three-process-bootstrap",
        "started_utc": utc_now(),
        "configuration": {
            "executable": str(config.executable),
            "install_dir": str(config.install_dir),
            "map_path": str(config.map_path),
            "expected_version": config.expected_version,
            "base_port": config.base_port,
            "setup_sequence_opt_in": config.setup_sequence,
            "observer_player_id": config.observer_player_id,
            "player_races": config.player_races,
            "player_port_sets": config.player_port_sets,
        },
        "map": {"sha256": sha256_file(config.map_path), "size_bytes": config.map_path.stat().st_size},
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
        for ordinal, role in enumerate(("observer", "player-1", "player-2")):
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
                for ordinal, role in enumerate(("observer", "player-1", "player-2")):
                    live_connections[role] = create_connection(
                        f"ws://127.0.0.1:{config.base_port + ordinal}/sc2api",
                        timeout=min(10.0, config.startup_timeout),
                        enable_multithread=False,
                    )
                manifest["gates"]["setup_sequence"] = {"attempted": True, "passed": False}
                run_observer_setup_sequence(
                    live_connections, sc2api_pb2,
                    map_path=str(config.map_path),
                    observer_player_id=config.observer_player_id,
                    player_races=config.player_races,
                    player_port_sets=config.player_port_sets,
                    timeout=min(10.0, config.startup_timeout),
                    manifest=manifest,
                    manifest_path=config.output_dir / "evidence.json",
                )
                manifest["gates"]["setup_sequence"] = {"attempted": True, "passed": True}
                manifest["status"] = "live-setup-sequence-passed"
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
    parser.add_argument("--observer-player-id", type=int)
    parser.add_argument("--player-1-race", type=int)
    parser.add_argument("--player-2-race", type=int)
    parser.add_argument("--player-1-server-ports", help="Explicit game_port,base_port pair")
    parser.add_argument("--player-2-server-ports", help="Explicit game_port,base_port pair")
    parser.add_argument("--player-1-client-ports", action="append", default=[], help="Explicit game_port,base_port pair; repeat as needed")
    parser.add_argument("--player-2-client-ports", action="append", default=[], help="Explicit game_port,base_port pair; repeat as needed")
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
    if args.setup_sequence:
        setup_required = {
            "--observer-player-id": args.observer_player_id,
            "--player-1-race": args.player_1_race,
            "--player-2-race": args.player_2_race,
            "--player-1-server-ports": args.player_1_server_ports,
            "--player-2-server-ports": args.player_2_server_ports,
        }
        missing_setup = [name for name, value in setup_required.items() if value is None]
        if missing_setup:
            print("Setup sequence requires: " + ", ".join(missing_setup), file=sys.stderr)
            return 2
        try:
            player_port_sets = {
                "player-1": {"server_ports": parse_port_pair(args.player_1_server_ports), "client_ports": tuple(parse_port_pair(v) for v in args.player_1_client_ports)},
                "player-2": {"server_ports": parse_port_pair(args.player_2_server_ports), "client_ports": tuple(parse_port_pair(v) for v in args.player_2_client_ports)},
            }
        except argparse.ArgumentTypeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        player_races = {"player-1": args.player_1_race, "player-2": args.player_2_race}
    else:
        if any(value is not None for value in (args.observer_player_id, args.player_1_race, args.player_2_race, args.player_1_server_ports, args.player_2_server_ports)) or args.player_1_client_ports or args.player_2_client_ports:
            print("Setup inputs require --setup-sequence.", file=sys.stderr)
            return 2
        player_port_sets = None
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
        setup_sequence=args.setup_sequence,
        observer_player_id=args.observer_player_id,
        player_races=player_races,
        player_port_sets=player_port_sets,
    )
    return run_probe(config)


if __name__ == "__main__":
    raise SystemExit(main())
