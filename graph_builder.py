"""Build an auditable graph seed and optionally write it to Neo4j."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import CONFIG, load_config, project_path
from .pipeline import run_pipeline
from .utils import json_dump, now_iso, normalize_credit_code

NODE_KEYS: dict[str, str] = {
    "Company": "company_id",
    "CompanyAlias": "alias_id",
    "Person": "person_id",
    "ExternalOrganization": "organization_id",
    "Patent": "patent_id",
    "Region": "region_code",
    "MergeCandidate": "candidate_id",
}

CONSTRAINTS: dict[str, str] = {
    "company_id_unique": "Company",
    "company_alias_id_unique": "CompanyAlias",
    "person_id_unique": "Person",
    "external_org_id_unique": "ExternalOrganization",
    "patent_id_unique": "Patent",
    "region_code_unique": "Region",
    "merge_candidate_id_unique": "MergeCandidate",
}


def _node(label: str, key_value: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "key": NODE_KEYS[label],
        "key_value": key_value,
        "properties": properties,
    }


def _relationship(
    from_label: str,
    from_key: str,
    to_label: str,
    to_key: str,
    rel_type: str,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "from_label": from_label,
        "from_key": from_key,
        "to_label": to_label,
        "to_key": to_key,
        "type": rel_type,
        "properties": properties,
    }


def build_graph_seed(entities: dict[str, Any], matching: dict[str, Any]) -> dict[str, Any]:
    project = "EnterpriseKG"
    canonical = matching["canonical_companies"]
    alias_records = matching["aliases"]
    resolved = {item["mention_id"]: item for item in matching["resolved_mentions"]}
    resolved_org_sources = {
        item["source_id"]
        for item in matching["resolved_mentions"]
        if item["source_type"] == "shareholder_org"
    }

    nodes: dict[str, list[dict[str, Any]]] = {label: [] for label in NODE_KEYS}
    rels: list[dict[str, Any]] = []

    for company in canonical:
        aliases = list(dict.fromkeys(company.get("alias_names", [])))
        properties = {
            "company_id": company["company_id"],
            "name": company["name"],
            "normalized_name": company["normalized_name"],
            "credit_code": normalize_credit_code(company.get("credit_code", "")) or None,
            "legal_representative": company.get("legal_representative", ""),
            "registered_capital": float(company.get("registered_capital", 0) or 0),
            "established_date": company.get("established_date", ""),
            "region_code": company.get("region_code", ""),
            "industry": company.get("industry", ""),
            "status": company.get("status", ""),
            "old_name": company.get("old_name", ""),
            "credit_code_missing": bool(company.get("credit_code_missing", False)),
            "source_company_ids": list(company.get("source_company_ids", [])),
            "aliases": aliases,
            "quality_flags": list(company.get("quality_flags", [])),
            "project": project,
        }
        nodes["Company"].append(_node("Company", str(company["company_id"]), properties))

    for alias in alias_records:
        properties = {
            "alias_id": alias["alias_id"],
            "canonical_company_id": alias["canonical_company_id"],
            "name": alias["name"],
            "normalized_name": alias["normalized_name"],
            "alias_type": alias["alias_type"],
            "source_company_id": alias["source_company_id"],
            "credit_code": alias.get("credit_code") or None,
            "confidence": float(alias.get("confidence", 0)),
            "method": alias.get("method", ""),
            "project": project,
        }
        nodes["CompanyAlias"].append(_node("CompanyAlias", str(alias["alias_id"]), properties))

    for person in entities["persons"]:
        properties = {
            "person_id": person["person_id"],
            "name": person["name"],
            "normalized_name": person["normalized_name"],
            "project": project,
        }
        nodes["Person"].append(_node("Person", str(person["person_id"]), properties))

    for organization in entities["external_organizations"]:
        source_ids = set(organization.get("source_ids", []))
        if source_ids and source_ids.issubset(resolved_org_sources):
            continue
        properties = {
            "organization_id": organization["organization_id"],
            "name": organization["name"],
            "normalized_name": organization["normalized_name"],
            "credit_code": normalize_credit_code(organization.get("credit_code", "")) or None,
            "project": project,
        }
        nodes["ExternalOrganization"].append(
            _node("ExternalOrganization", str(organization["organization_id"]), properties)
        )

    for patent in entities["patents"]:
        properties = {
            "patent_id": patent["patent_id"],
            "patent_name": patent["patent_name"],
            "patent_number": patent["patent_number"],
            "application_date": patent["application_date"],
            "applicant_name": patent["applicant_name"],
            "patent_type": patent["patent_type"],
            "status": patent["status"],
            "project": project,
        }
        nodes["Patent"].append(_node("Patent", str(patent["patent_id"]), properties))

    for region in entities["regions"]:
        properties = {
            "region_code": region["region_code"],
            "province": region["province"],
            "city": region["city"],
            "district": region["district"],
            "region_label": region.get("region_label", ""),
            "project": project,
        }
        nodes["Region"].append(_node("Region", str(region["region_code"]), properties))

    for candidate in matching["company_pairs"]:
        properties = {
            "candidate_id": candidate["candidate_id"],
            "candidate_type": candidate["candidate_type"],
            "left_company_id": candidate["left_id"],
            "left_name": candidate["left_name"],
            "right_company_id": candidate["right_id"],
            "right_name": candidate["right_name"],
            "score": float(candidate["score"]),
            "name_score": float(candidate["name_score"]),
            "confidence_tier": candidate["confidence_tier"],
            "decision": candidate["decision"],
            "conflicts": list(candidate.get("conflicts", [])),
            "reasons": list(candidate.get("reasons", [])),
            "project": project,
        }
        nodes["MergeCandidate"].append(
            _node("MergeCandidate", str(candidate["candidate_id"]), properties)
        )
        rels.append(
            _relationship(
                "Company",
                candidate["left_id"],
                "Company",
                candidate["right_id"],
                "SUSPECTED_DUPLICATE",
                {
                    "candidate_id": candidate["candidate_id"],
                    "score": float(candidate["score"]),
                    "confidence_tier": candidate["confidence_tier"],
                    "decision": candidate["decision"],
                    "conflicts": list(candidate.get("conflicts", [])),
                },
            )
        )

    company_by_id = {str(item["company_id"]): item for item in canonical}
    for company in canonical:
        region_code = str(company.get("region_code", ""))
        if region_code:
            rels.append(
                _relationship(
                    "Company",
                    str(company["company_id"]),
                    "Region",
                    region_code,
                    "LOCATED_IN",
                    {"source": "companies.csv"},
                )
            )

    person_ids = {str(item["person_id"]) for item in entities["persons"]}
    external_org_ids = {
        str(item["organization_id"])
        for item in entities["external_organizations"]
        if str(item["organization_id"]) in {node["key_value"] for node in nodes["ExternalOrganization"]}
    }
    for fact in entities["relationships"]["shareholding"]:
        target = resolved.get(fact["target_mention_id"])
        if not target:
            continue
        company_id = target["company_id"]
        if company_id not in company_by_id:
            continue

        from_label = ""
        from_key = ""
        if fact["from_type"] == "natural_person" and fact["from_id"] in person_ids:
            from_label, from_key = "Person", fact["from_id"]
        elif fact["from_type"] == "enterprise":
            holder_target = resolved.get(fact.get("holder_mention_id", ""))
            if holder_target and holder_target["company_id"] in company_by_id:
                from_label, from_key = "Company", holder_target["company_id"]
            elif fact["from_id"] in external_org_ids:
                from_label, from_key = "ExternalOrganization", fact["from_id"]
        if not from_label:
            continue

        rels.append(
            _relationship(
                from_label,
                from_key,
                "Company",
                company_id,
                "HOLDS_SHARES",
                {
                    "percentage": float(fact.get("percentage", 0) or 0),
                    "amount": float(fact.get("amount", 0) or 0),
                    "date": fact.get("date", ""),
                    "shareholder_id": fact["shareholder_id"],
                },
            )
        )

    for fact in entities["relationships"]["patent_ownership"]:
        target = resolved.get(fact["mention_id"])
        if not target:
            continue
        rels.append(
            _relationship(
                "Company",
                target["company_id"],
                "Patent",
                fact["patent_id"],
                "OWNS_PATENT",
                {
                    "score": float(target.get("score", 0)),
                    "method": target.get("method", ""),
                    "applicant_name": fact.get("applicant_name", ""),
                },
            )
        )

    for alias in alias_records:
        rels.append(
            _relationship(
                "Company",
                alias["canonical_company_id"],
                "CompanyAlias",
                alias["alias_id"],
                "HAS_ALIAS",
                {
                    "alias_type": alias["alias_type"],
                    "confidence": float(alias.get("confidence", 0)),
                },
            )
        )

    # Deduplicate relationships while keeping the first occurrence.
    unique_rels: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for rel in rels:
        key = (
            rel["from_label"],
            rel["from_key"],
            rel["to_label"],
            rel["to_key"],
            rel["type"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rels.append(rel)

    node_counts = {label: len(items) for label, items in nodes.items()}
    rel_counts: dict[str, int] = defaultdict(int)
    for rel in unique_rels:
        rel_counts[rel["type"]] += 1

    seed = {
        "generated_at": now_iso(),
        "project": project,
        "nodes": nodes,
        "relationships": unique_rels,
        "meta": {
            "node_counts": node_counts,
            "relationship_counts": dict(sorted(rel_counts.items())),
            "patent_links": sum(1 for rel in unique_rels if rel["type"] == "OWNS_PATENT"),
            "unresolved_patent_mentions": [
                item
                for item in matching.get("review_mentions", [])
                if item["source_type"] == "patent_applicant"
            ],
            "unresolved_external_orgs": len(nodes["ExternalOrganization"]),
        },
    }
    return seed


def write_seed(seed: dict[str, Any], config: dict[str, Any]) -> Path:
    path = project_path(config, "output_dir") / "graph_seed.json"
    json_dump(path, seed)
    return path


def _neo4j_endpoint(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    return parsed.hostname or "127.0.0.1", parsed.port or 7687


def _port_open(uri: str, timeout: float = 1.0) -> bool:
    host, port = _neo4j_endpoint(uri)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def write_to_neo4j(seed: dict[str, Any], config: dict[str, Any], *, reset: bool = False) -> dict[str, Any]:
    from neo4j import GraphDatabase

    neo4j_config = config["neo4j"]
    uri = str(neo4j_config["uri"])
    if not _port_open(uri):
        raise ConnectionError(f"Neo4j Bolt port is not reachable at {uri}")

    driver = GraphDatabase.driver(
        uri,
        auth=(str(neo4j_config["user"]), str(neo4j_config["password"])),
        connection_timeout=float(neo4j_config.get("connection_timeout", 3)),
    )
    database = str(neo4j_config.get("database", "neo4j"))
    project = str(seed["project"])

    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            if reset:
                session.run(
                    "MATCH (n {project: $project}) DETACH DELETE n",
                    project=project,
                ).consume()

            for constraint_name, label in CONSTRAINTS.items():
                key = NODE_KEYS[label]
                session.run(
                    f"CREATE CONSTRAINT `{constraint_name}` IF NOT EXISTS "
                    f"FOR (n:`{label}`) REQUIRE n.`{key}` IS UNIQUE"
                ).consume()

            for label, key in NODE_KEYS.items():
                rows = [
                    {**node["properties"], key: node["key_value"]}
                    for node in seed["nodes"].get(label, [])
                ]
                if not rows:
                    continue
                session.run(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:`{label}` {{`{key}`: row.`{key}`}}) "
                    f"SET n += row",
                    rows=rows,
                ).consume()

            grouped_rels: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
            for rel in seed["relationships"]:
                grouped_rels[
                    (rel["from_label"], rel["to_label"], rel["type"], "")
                ].append(rel)

            for (from_label, to_label, rel_type, _), rows in grouped_rels.items():
                if from_label not in NODE_KEYS or to_label not in NODE_KEYS:
                    raise ValueError(f"Unsupported relationship labels: {from_label}->{to_label}")
                from_key = NODE_KEYS[from_label]
                to_key = NODE_KEYS[to_label]
                payload = [
                    {
                        "from_key": rel["from_key"],
                        "to_key": rel["to_key"],
                        "props": rel["properties"],
                    }
                    for rel in rows
                ]
                session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:`{from_label}` {{`{from_key}`: row.from_key}}) "
                    f"MATCH (b:`{to_label}` {{`{to_key}`: row.to_key}}) "
                    f"MERGE (a)-[r:`{rel_type}`]->(b) "
                    f"SET r += row.props",
                    rows=payload,
                ).consume()

            record = session.run(
                "MATCH (n {project: $project}) RETURN count(n) AS node_count",
                project=project,
            ).single()
            node_count = int(record["node_count"]) if record else 0
        return {"node_count": node_count, "uri": uri, "database": database}
    finally:
        driver.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build EnterpriseKG graph seed / Neo4j graph.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    parser.add_argument("--offline", action="store_true", help="Only write the offline graph seed")
    parser.add_argument("--reset", action="store_true", help="Delete existing EnterpriseKG nodes first")
    parser.add_argument("--require-neo4j", action="store_true", help="Fail if Neo4j is unavailable")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    result = run_pipeline(config, write=True)
    seed = build_graph_seed(result["entities"], result["matching"])
    seed_path = write_seed(seed, config)

    status: dict[str, Any] = {
        "generated_at": now_iso(),
        "mode": "offline",
        "neo4j": {"connected": False, "reason": "offline flag"},
        "seed_path": str(seed_path),
        "counts": seed["meta"]["node_counts"],
        "relationship_counts": seed["meta"]["relationship_counts"],
    }

    if not args.offline:
        try:
            neo4j_result = write_to_neo4j(seed, config, reset=args.reset)
            status["mode"] = "neo4j"
            status["neo4j"] = {"connected": True, **neo4j_result}
        except Exception as exc:  # noqa: BLE001 - surfaced as a clear offline fallback
            status["neo4j"] = {
                "connected": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            if args.require_neo4j:
                status_path = project_path(config, "output_dir") / "graph_build_status.json"
                json_dump(status_path, status)
                print(json.dumps(status, ensure_ascii=False, indent=2))
                return 2

    status_path = project_path(config, "output_dir") / "graph_build_status.json"
    json_dump(status_path, status)
    status["status_path"] = str(status_path)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
