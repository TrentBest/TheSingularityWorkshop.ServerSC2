import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from contract_report_to_trx import NS, convert


class ContractReportTrxTests(unittest.TestCase):
    def setUp(self):
        self.started = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        self.finished = datetime(2026, 11, 20, 12, 0, 1, tzinfo=timezone.utc)

    def test_preserves_each_passed_and_failed_check(self):
        payload = convert({
            "checks": [
                {"name": "valid contract", "status": "passed"},
                {"name": "invalid contract", "status": "failed", "failure": "assertion failed"},
            ]
        }, self.started, self.finished)
        root = ET.fromstring(payload)
        results = root.find(f"{{{NS}}}Results")
        self.assertEqual([node.attrib["outcome"] for node in results], ["Passed", "Failed"])
        self.assertEqual([node.attrib["testName"] for node in results],
                         ["valid contract", "invalid contract"])
        message = root.find(f".//{{{NS}}}Message")
        self.assertEqual(message.text, "assertion failed")

    def test_unknown_status_is_not_promoted_to_pass(self):
        root = ET.fromstring(convert({"checks": [{"name": "future status", "status": "future"}]},
                                     self.started, self.finished))
        result = root.find(f".//{{{NS}}}UnitTestResult")
        self.assertEqual(result.attrib["outcome"], "NotExecuted")
        summary = root.find(f"{{{NS}}}ResultSummary")
        self.assertEqual(summary.attrib["outcome"], "Failed")

    def test_rejects_duplicate_names_and_unbounded_result_count(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            convert({"checks": [{"name": "same", "status": "passed"},
                                {"name": "same", "status": "passed"}]},
                    self.started, self.finished)
        with self.assertRaisesRegex(ValueError, "exceeds-limit"):
            convert({"checks": [{}] * 10001}, self.started, self.finished)

    def test_rejects_invalid_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timestamps"):
            convert({"checks": []}, self.finished, self.started)


if __name__ == "__main__":
    unittest.main()
