"""Quality-gate tests; no Neo4j connection is attempted."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CONFIG
from src.quality_check import run_quality_checks


class QualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_quality_checks(CONFIG, check_neo4j=False, write_report=False)

    def test_no_failed_checks(self) -> None:
        failures = [item for item in self.report["checks"] if item["status"] == "FAIL"]
        self.assertEqual(failures, [])

    def test_quality_report_exposes_candidates(self) -> None:
        self.assertGreaterEqual(len(self.report["suspected_unmerged_pairs"]), 3)
        conflict_names = {
            conflict
            for pair in self.report["suspected_unmerged_pairs"]
            for conflict in pair["conflicts"]
        }
        self.assertIn("different_credit_code", conflict_names)
        self.assertIn("missing_credit_code", conflict_names)

    def test_overall_status_is_pass(self) -> None:
        self.assertIn(self.report["overall_status"], {"PASS", "PASS_WITH_WARNINGS"})


if __name__ == "__main__":
    unittest.main()
