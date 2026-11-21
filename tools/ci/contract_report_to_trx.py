#!/usr/bin/env python3
"""Convert the contract harness JSON report into bounded, parser-compatible TRX XML.

This is a report adapter, not a VSTest runner. It preserves each named contract
check and its outcome so CiAi can consume the existing executable harness.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"
ET.register_namespace("", NS)


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def convert(report: dict, started: datetime | None = None, finished: datetime | None = None) -> bytes:
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ValueError("contract-report.checks.invalid")
    if len(checks) > 10000:
        raise ValueError("contract-report.check-count.exceeds-limit")

    started = started or datetime.now(timezone.utc)
    finished = finished or datetime.now(timezone.utc)
    if started.tzinfo is None or finished.tzinfo is None or finished < started:
        raise ValueError("contract-report.timestamps.invalid")

    run_id = str(uuid.uuid4())
    root = ET.Element(_tag("TestRun"), {
        "id": run_id,
        "name": "ServerSC2 contract checks",
        "runUser": "GitHub Actions",
    })
    results = ET.SubElement(root, _tag("Results"))
    definitions = ET.SubElement(root, _tag("TestDefinitions"))
    entries = ET.SubElement(root, _tag("TestEntries"))
    counters = {"passed": 0, "failed": 0, "notExecuted": 0}
    seen: set[str] = set()

    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError("contract-report.check.invalid")
        name = check.get("name")
        status = check.get("status")
        if not isinstance(name, str) or not name.strip() or len(name) > 512:
            raise ValueError("contract-report.check-name.invalid")
        if name in seen:
            raise ValueError("contract-report.check-name.duplicate")
        seen.add(name)
        outcome = {"passed": "Passed", "failed": "Failed"}.get(status, "NotExecuted")
        counters[{"Passed": "passed", "Failed": "failed"}.get(outcome, "notExecuted")] += 1
        test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "server-sc2-contract:" + name))
        execution_id = str(uuid.uuid5(uuid.UUID(run_id), str(index)))
        duration = "00:00:00"
        unit_result = ET.SubElement(results, _tag("UnitTestResult"), {
            "executionId": execution_id,
            "testId": test_id,
            "testName": name,
            "computerName": "GitHub Actions",
            "duration": duration,
            "startTime": _timestamp(started),
            "endTime": _timestamp(finished),
            "outcome": outcome,
            "testType": "13cdc9d9-ddb5-4fa4-a97d-d965ccfc6d4b",
            "testListId": "00000000-0000-0000-0000-000000000000",
            "relativeResultsDirectory": execution_id,
        })
        unit_test = ET.SubElement(definitions, _tag("UnitTest"), {
            "name": name,
            "id": test_id,
            "storage": "ServerSC2.ContractChecks",
        })
        ET.SubElement(unit_test, _tag("Execution"), {"id": execution_id})
        ET.SubElement(unit_test, _tag("TestMethod"), {
            "codeBase": "ServerSC2.ContractChecks",
            "adapterTypeName": "ServerSC2 contract report adapter",
            "className": "ServerSC2.ContractChecks",
            "name": name,
        })
        ET.SubElement(entries, _tag("TestEntry"), {
            "testId": test_id,
            "executionId": execution_id,
            "testListId": "00000000-0000-0000-0000-000000000000",
        })
        failure = check.get("failure")
        if outcome == "Failed":
            output = ET.SubElement(unit_result, _tag("Output"))
            error = ET.SubElement(output, _tag("ErrorInfo"))
            ET.SubElement(error, _tag("Message")).text = str(failure or "Contract check failed")[:4096]
            ET.SubElement(error, _tag("StackTrace")).text = str(failure or "")[:4096]

    total = len(checks)
    summary = ET.SubElement(root, _tag("ResultSummary"), {
        "outcome": "Failed" if counters["failed"] or counters["notExecuted"] else "Passed",
    })
    ET.SubElement(summary, _tag("Counters"), {
        "total": str(total),
        "executed": str(counters["passed"] + counters["failed"]),
        "passed": str(counters["passed"]),
        "failed": str(counters["failed"]),
        "error": "0",
        "timeout": "0",
        "aborted": "0",
        "inconclusive": "0",
        "passedButRunAborted": "0",
        "notRunnable": "0",
        "notExecuted": str(counters["notExecuted"]),
        "disconnected": "0",
        "warning": "0",
        "completed": str(counters["passed"] + counters["failed"]),
        "inProgress": "0",
        "pending": "0",
    })
    ET.SubElement(summary, _tag("RunInfos"))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    payload = convert(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(args.output)
    print(f"Wrote {len(report['checks'])} contract results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
