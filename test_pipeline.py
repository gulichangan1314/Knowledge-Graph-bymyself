"""Contract tests for the synthetic data and entity-alignment rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CONFIG
from src.entity_matcher import match_entities
from src.pipeline import run_pipeline
from src.utils import normalize_credit_code


class PipelineAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_pipeline(CONFIG, write=False)
        cls.entities = cls.result["entities"]
        cls.matching = cls.result["matching"]
        cls.companies = cls.result["clean"].companies
        cls.plain_companies = cls.result["raw"].companies
        cls.shareholders = cls.result["raw"].shareholders
        cls.patents = cls.result["raw"].patents
        cls.regions = cls.result["raw"].regions

    def test_expected_row_counts(self) -> None:
        self.assertEqual(len(self.plain_companies), 8)
        self.assertEqual(len(self.shareholders), 10)
        self.assertEqual(len(self.patents), 8)
        self.assertEqual(len(self.regions), 3)

    def test_data_problems_are_intentionally_present(self) -> None:
        missing = self.companies[self.companies["credit_code_missing"]]
        self.assertEqual(missing["company_id"].tolist(), ["C008"])

        same_code = (
            self.companies[self.companies["credit_code"] != ""]
            .groupby("credit_code")
            .size()
        )
        self.assertEqual(int((same_code == 2).sum()), 1)
        self.assertEqual(int((same_code > 2).sum()), 0)

    def test_two_near_name_conflicts_are_detected(self) -> None:
        conflicts = [
            pair for pair in self.matching["company_pairs"]
            if "different_credit_code" in pair["conflicts"]
        ]
        ids = {pair["candidate_id"] for pair in conflicts}
        self.assertIn("PAIR-C001-C002", ids)
        self.assertIn("PAIR-C003-C004", ids)
        self.assertGreaterEqual(len(conflicts), 2)

    def test_same_code_name_variant_is_merged(self) -> None:
        canonical_ids = {company["company_id"] for company in self.matching["canonical_companies"]}
        self.assertIn("C005", canonical_ids)
        self.assertNotIn("C006", canonical_ids)
        self.assertEqual(self.matching["stats"]["merged_variant_records"], 1)
        variant = [
            alias for alias in self.matching["aliases"]
            if alias["alias_type"] == "same_code_variant"
        ]
        self.assertTrue(
            any(
                alias["canonical_company_id"] == "C005"
                and alias["source_company_id"] == "C006"
                for alias in variant
            )
        )

    def test_old_name_patents_resolve(self) -> None:
        resolved = {item["source_id"]: item for item in self.matching["resolved_mentions"]}
        self.assertEqual(resolved["P003"]["company_id"], "C003")
        self.assertEqual(resolved["P007"]["company_id"], "C007")
        self.assertEqual(resolved["P005"]["company_id"], "C005")

    def test_missing_code_patent_stays_in_review(self) -> None:
        review = {item["source_id"]: item for item in self.matching["review_mentions"]}
        self.assertIn("P008", review)
        self.assertIn("missing_credit_code", review["P008"]["conflicts"])
        resolved = {item["source_id"] for item in self.matching["resolved_mentions"]}
        self.assertNotIn("P008", resolved)

    def test_no_auto_merge_across_different_codes(self) -> None:
        for candidate in self.matching["mention_matches"]:
            if candidate["decision"] != "auto_merge":
                continue
            left = normalize_credit_code(candidate["left_credit_code"])
            right = normalize_credit_code(candidate["right_credit_code"])
            if left and right:
                self.assertEqual(left, right, candidate["candidate_id"])

    def test_company_pairs_never_auto_merge(self) -> None:
        self.assertTrue(self.matching["company_pairs"])
        for pair in self.matching["company_pairs"]:
            self.assertEqual(pair["decision"], "review")
            self.assertIn(pair["confidence_tier"], {"high", "medium", "low"})

    def test_alignment_engine_is_rapidfuzz(self) -> None:
        self.assertIn("rapidfuzz", self.matching["engine"].lower())


if __name__ == "__main__":
    unittest.main()
