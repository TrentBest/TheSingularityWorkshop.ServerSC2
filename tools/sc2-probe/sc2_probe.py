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
    event = {
        "transport": "websocket",
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

        # This bootstrap milestone intentionally stops before CreateGame/join. Those
        # messages and the complete PortSet payload remain live-proof gates, not guesses.
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
    return parser.parse_args(argv)


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
    config = ProbeConfig(
        executable=args.executable.resolve(),
        install_dir=args.install_dir.resolve(),
        map_path=args.map_path.resolve(),
        output_dir=args.output_dir.resolve(),
        expected_version=args.expected_version,
        base_port=args.base_port,
        startup_timeout=args.startup_timeout,
        shutdown_timeout=args.shutdown_timeout,
    )
    return run_probe(config)


if __name__ == "__main__":
    raise SystemExit(main())
