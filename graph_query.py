"""Read-only Cypher presets and an offline graph preview."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from .config import CONFIG, load_config, project_path
from .utils import json_load, now_iso

CYPHER_QUERIES: "OrderedDict[str, dict[str, str]]" = OrderedDict(
    [
        (
            "overview",
            {
                "title": "企业总览：信用代码、行业、专利与别名",
                "cypher": """
MATCH (c:Company)
OPTIONAL MATCH (c)-[:OWNS_PATENT]->(p:Patent)
OPTIONAL MATCH (c)-[:HAS_ALIAS]->(a:CompanyAlias)
RETURN c.name AS company,
       coalesce(c.credit_code, '(missing)') AS credit_code,
       c.industry AS industry,
       count(DISTINCT p) AS patents,
       count(DISTINCT a) AS aliases
ORDER BY patents DESC, company
""".strip(),
            },
        ),
        (
            "duplicates",
            {
                "title": "疑似未合并：名称接近但信用代码冲突/缺失",
                "cypher": """
MATCH (a:Company)-[r:SUSPECTED_DUPLICATE]->(b:Company)
RETURN a.name AS company_a,
       coalesce(a.credit_code, '(missing)') AS credit_code_a,
       b.name AS company_b,
       coalesce(b.credit_code, '(missing)') AS credit_code_b,
       r.score AS score,
       r.confidence_tier AS confidence,
       r.decision AS decision,
       r.conflicts AS conflicts
ORDER BY score DESC, company_a
""".strip(),
            },
        ),
        (
            "chain",
            {
                "title": "股权—专利二跳链路",
                "cypher": """
MATCH (holder)-[h:HOLDS_SHARES]->(c:Company)-[o:OWNS_PATENT]->(p:Patent)
RETURN labels(holder)[0] AS holder_type,
       holder.name AS holder,
       c.name AS company,
       p.patent_name AS patent,
       h.percentage AS ownership_pct,
       o.score AS alignment_score
ORDER BY company, holder, patent
""".strip(),
            },
        ),
        (
            "aliases",
            {
                "title": "同代码名称变体与曾用名",
                "cypher": """
MATCH (c:Company)-[r:HAS_ALIAS]->(a:CompanyAlias)
RETURN c.name AS company,
       c.credit_code AS credit_code,
       a.name AS alias,
       a.alias_type AS alias_type,
       r.confidence AS confidence
ORDER BY company, alias_type, alias
""".strip(),
            },
        ),
    ]
)


def _endpoint(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    return parsed.hostname or "127.0.0.1", parsed.port or 7687


def _port_open(uri: str, timeout: float = 1.0) -> bool:
    host, port = _endpoint(uri)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_query(
    cypher: str,
    params: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    config = config or CONFIG
    from neo4j import GraphDatabase

    neo4j_config = config["neo4j"]
    uri = str(neo4j_config["uri"])
    driver = GraphDatabase.driver(
        uri,
        auth=(str(neo4j_config["user"]), str(neo4j_config["password"])),
        connection_timeout=float(neo4j_config.get("connection_timeout", 3)),
    )
    try:
        driver.verify_connectivity()
        with driver.session(database=str(neo4j_config.get("database", "neo4j"))) as session:
            result = session.run(cypher, params or {})
            return [record.data() for record in result]
    finally:
        driver.close()


def _offline_preview(config: dict[str, Any], preset: str) -> int:
    output_dir = project_path(config, "output_dir")
    seed_path = output_dir / "graph_seed.json"
    if not seed_path.is_file():
        print("[INFO] Offline seed not found; building it now ...")
        from .graph_builder import build_graph_seed, write_seed
        from .pipeline import run_pipeline

        result = run_pipeline(config, write=True)
        seed = build_graph_seed(result["entities"], result["matching"])
        write_seed(seed, config)
    else:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))

    print(json.dumps({"mode": "offline", "source": str(seed_path), "generated_at": now_iso()}, ensure_ascii=False, indent=2))
    print("Node counts:", json.dumps(seed["meta"]["node_counts"], ensure_ascii=False))
    print("Relationship counts:", json.dumps(seed["meta"]["relationship_counts"], ensure_ascii=False))

    if preset == "duplicates":
        rows = []
        for node in seed["nodes"]["MergeCandidate"]:
            props = node["properties"]
            rows.append(
                {
                    "company_a": props["left_name"],
                    "company_b": props["right_name"],
                    "score": props["score"],
                    "confidence": props["confidence_tier"],
                    "decision": props["decision"],
                    "conflicts": ", ".join(props.get("conflicts", [])),
                }
            )
        if rows:
            print(pd.DataFrame(rows).to_string(index=False))
    elif preset == "overview":
        rows = [
            {
                "company": node["properties"]["name"],
                "credit_code": node["properties"].get("credit_code") or "(missing)",
                "industry": node["properties"].get("industry"),
            }
            for node in seed["nodes"]["Company"]
        ]
        print(pd.DataFrame(rows).to_string(index=False))
    elif preset == "aliases":
        rows = [
            {
                "company_id": node["properties"]["canonical_company_id"],
                "alias": node["properties"]["name"],
                "alias_type": node["properties"]["alias_type"],
            }
            for node in seed["nodes"]["CompanyAlias"]
        ]
        print(pd.DataFrame(rows).to_string(index=False))
    else:
        print("\nCypher preset (run after Neo4j is available):\n")
        print(CYPHER_QUERIES[preset]["cypher"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the EnterpriseKG Neo4j graph.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    parser.add_argument("--list", action="store_true", help="List built-in queries")
    parser.add_argument("--preset", choices=list(CYPHER_QUERIES), default="overview")
    parser.add_argument("--query", help="Run a custom read-only Cypher query")
    parser.add_argument("--offline", action="store_true", help="Preview the offline seed instead")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG

    if args.list:
        for name, item in CYPHER_QUERIES.items():
            print(f"{name}: {item['title']}")
        return 0

    if args.offline:
        return _offline_preview(config, args.preset)

    cypher = args.query or CYPHER_QUERIES[args.preset]["cypher"]
    uri = str(config["neo4j"]["uri"])
    if not _port_open(uri):
        print(f"[WARN] Neo4j is not reachable at {uri}. Showing offline preview.")
        return _offline_preview(config, args.preset)

    try:
        rows = run_query(cypher, config=config)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Query failed: {type(exc).__name__}: {exc}")
        print("        Check Neo4j and credentials, or use --offline.")
        return 1

    if not rows:
        print("(no rows)")
        return 0
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
