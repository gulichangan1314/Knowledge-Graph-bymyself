"""Offline graph-seed integrity tests (no Neo4j required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CONFIG
from src.graph_builder import build_graph_seed
from src.pipeline import run_pipeline


class GraphSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = run_pipeline(CONFIG, write=False)
        cls.seed = build_graph_seed(result["entities"], result["matching"])
        cls.nodes = {
            label: {node["key_value"]: node["properties"] for node in items}
            for label, items in cls.seed["nodes"].items()
        }

    def test_expected_node_counts(self) -> None:
        self.assertEqual(len(self.nodes["Company"]), 7)
        self.assertEqual(len(self.nodes["CompanyAlias"]), 3)
        self.assertEqual(len(self.nodes["Person"]), 6)
        self.assertEqual(len(self.nodes["ExternalOrganization"]), 4)
        self.assertEqual(len(self.nodes["Patent"]), 8)
        self.assertEqual(len(self.nodes["Region"]), 3)

    def test_all_relationship_endpoints_exist(self) -> None:
        for rel in self.seed["relationships"]:
            self.assertIn(rel["from_key"], self.nodes[rel["from_label"]])
            self.assertIn(rel["to_key"], self.nodes[rel["to_label"]])

    def test_expected_relationship_counts(self) -> None:
        counts = self.seed["meta"]["relationship_counts"]
        self.assertEqual(counts["HOLDS_SHARES"], 10)
        self.assertEqual(counts["OWNS_PATENT"], 7)
        self.assertEqual(counts["HAS_ALIAS"], 3)
        self.assertGreaterEqual(counts["SUSPECTED_DUPLICATE"], 3)
        self.assertEqual(counts["LOCATED_IN"], 7)

    def test_similar_but_different_credit_companies_remain_separate(self) -> None:
        self.assertIn("C001", self.nodes["Company"])
        self.assertIn("C002", self.nodes["Company"])
        self.assertIn("C003", self.nodes["Company"])
        self.assertIn("C004", self.nodes["Company"])
        self.assertNotEqual(
            self.nodes["Company"]["C001"]["credit_code"],
            self.nodes["Company"]["C002"]["credit_code"],
        )

    def test_same_code_variant_has_no_company_node(self) -> None:
        self.assertNotIn("C006", self.nodes["Company"])
        company = self.nodes["Company"]["C005"]
        self.assertIn("蓝海数据服务（深圳）有限公司", company["aliases"])

    def test_missing_credit_company_is_kept_without_fake_code(self) -> None:
        company = self.nodes["Company"]["C008"]
        self.assertIsNone(company["credit_code"])
        self.assertTrue(company["credit_code_missing"])

    def test_p008_patent_is_not_linked(self) -> None:
        links = {
            rel["to_key"]
            for rel in self.seed["relationships"]
            if rel["type"] == "OWNS_PATENT"
        }
        self.assertIn("P003", links)
        self.assertIn("P007", links)
        self.assertNotIn("P008", links)


if __name__ == "__main__":
    unittest.main()
