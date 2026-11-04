"""Quality gate: data contract, alignment safety, graph integrity, optional Neo4j."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from .config import CONFIG, load_config, project_path
from .graph_builder import build_graph_seed, write_seed
from .pipeline import run_pipeline
from .utils import json_dump, normalize_credit_code, now_iso

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def _check(
    name: str,
    status: str,
    detail: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "metrics": metrics or {},
    }


def _port_open(uri: str, timeout: float = 1.0) -> bool:
    parsed = urlparse(uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _neo4j_check(config: dict[str, Any], expect_companies: int) -> dict[str, Any]:
    uri = str(config["neo4j"]["uri"])
    if not _port_open(uri):
        return _check(
            "Neo4j 图数据库校验",
            WARN,
            f"Neo4j Bolt 端口不可达（{uri}），已跳过在线校验；离线图种子校验已通过",
            {"connected": False},
        )

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri,
            auth=(str(config["neo4j"]["user"]), str(config["neo4j"]["password"])),
            connection_timeout=float(config["neo4j"].get("connection_timeout", 3)),
        )
        try:
            driver.verify_connectivity()
            with driver.session(database=str(config["neo4j"].get("database", "neo4j"))) as session:
                counts = {
                    record["label"]: record["count"]
                    for record in session.run(
                        "MATCH (n {project: $project}) "
                        "RETURN labels(n)[0] AS label, count(*) AS count",
                        project="EnterpriseKG",
                    )
                }
                duplicate_edges = session.run(
                    "MATCH (:Company)-[r:SUSPECTED_DUPLICATE]->(:Company) RETURN count(r) AS c"
                ).single()["c"]
            connected = True
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001
        return _check(
            "Neo4j 图数据库校验",
            WARN,
            f"连接失败，已跳过在线校验：{type(exc).__name__}: {exc}",
            {"connected": False},
        )

    expected = expect_companies
    actual = int(counts.get("Company", 0))
    status = PASS if actual == expected and int(duplicate_edges) >= 1 else FAIL
    return _check(
        "Neo4j 图数据库校验",
        status,
        f"Company 节点 {actual}/{expected}，疑似重复边 {int(duplicate_edges)}",
        {"connected": connected, "labels": counts, "suspected_duplicate_edges": int(duplicate_edges)},
    )


def run_quality_checks(
    config: dict[str, Any] | None = None,
    *,
    check_neo4j: bool = True,
    require_neo4j: bool = False,
    write_report: bool = True,
) -> dict[str, Any]:
    config = config or CONFIG
    pipeline = run_pipeline(config, write=True)
    raw = pipeline["raw"]
    clean = pipeline["clean"]
    matching = pipeline["matching"]
    seed = build_graph_seed(pipeline["entities"], matching)
    seed_path = write_seed(seed, config)
    quality = config.get("quality", {})
    expected_counts = quality.get("expected_counts", {})
    tolerance = float(quality.get("percentage_tolerance", 0.01))
    checks: list[dict[str, Any]] = []

    # 1. Row-count / schema contract.
    count_details: list[str] = []
    count_ok = True
    for table, expected in expected_counts.items():
        actual = int(len(raw.as_dict()[table]))
        count_details.append(f"{table}={actual}/{expected}")
        if actual != int(expected):
            count_ok = False
    checks.append(
        _check(
            "原始数据行数与契约",
            PASS if count_ok else FAIL,
            ", ".join(count_details),
            {"counts": raw.summary()},
        )
    )

    # 2. Primary-key uniqueness.
    duplicates: dict[str, int] = {}
    for table, key in (
        ("companies", "company_id"),
        ("shareholders", "shareholder_id"),
        ("patents", "patent_id"),
        ("regions", "region_code"),
    ):
        frame = raw.as_dict()[table]
        duplicates[table] = int(frame[key].duplicated().sum())
    checks.append(
        _check(
            "主键唯一性",
            PASS if not any(duplicates.values()) else FAIL,
            "所有主键唯一" if not any(duplicates.values()) else f"重复主键：{duplicates}",
            duplicates,
        )
    )

    # 3. Credit-code integrity: exactly one intentional missing record.
    companies = clean.companies
    missing_credit = companies[companies["credit_code_missing"]]
    invalid_credit = companies[
        (~companies["credit_code_missing"]) & (~companies["credit_code_valid"])
    ]
    credit_ok = len(missing_credit) == 1 and len(invalid_credit) == 0
    checks.append(
        _check(
            "信用代码完整性",
            PASS if credit_ok else FAIL,
            f"缺失 {len(missing_credit)} 条（预期 1），格式非法 {len(invalid_credit)} 条",
            {
                "missing_company_ids": missing_credit["company_id"].tolist(),
                "invalid_company_ids": invalid_credit["company_id"].tolist(),
            },
        )
    )

    # 4. Observable similarity evidence.
    differing = [
        pair for pair in matching["company_pairs"]
        if "different_credit_code" in pair.get("conflicts", [])
    ]
    pair_ids = {pair["candidate_id"] for pair in differing}
    required_conflicts = {"PAIR-C001-C002", "PAIR-C003-C004"}
    conflict_ok = required_conflicts.issubset(pair_ids)
    checks.append(
        _check(
            "近名但代码不同的冲突识别",
            PASS if conflict_ok else FAIL,
            f"识别到 {len(differing)} 对；关键样例 {sorted(required_conflicts)} "
            f"{'全部命中' if conflict_ok else '未全部命中'}",
            {"pairs": sorted(pair_ids)},
        )
    )

    # 5. Same-code name variant must become an alias, not a separate company.
    variant_aliases = [
        alias for alias in matching["aliases"]
        if alias["alias_type"] == "same_code_variant"
    ]
    variant_ok = any(
        alias["canonical_company_id"] == "C005"
        and alias["source_company_id"] == "C006"
        for alias in variant_aliases
    )
    checks.append(
        _check(
            "同代码不同名称自动归并",
            PASS if variant_ok else FAIL,
            f"同代码名称变体别名 {len(variant_aliases)} 条；C006→C005 "
            f"{'已建立' if variant_ok else '未建立'}",
            {
                "alias_pairs": [
                    [alias["canonical_company_id"], alias["source_company_id"]]
                    for alias in variant_aliases
                ]
            },
        )
    )

    # 6. Old names are resolved for patents.
    resolved_by_source = {
        item["source_id"]: item for item in matching["resolved_mentions"]
    }
    old_name_ok = (
        resolved_by_source.get("P003", {}).get("company_id") == "C003"
        and resolved_by_source.get("P007", {}).get("company_id") == "C007"
    )
    checks.append(
        _check(
            "曾用名对齐",
            PASS if old_name_ok else FAIL,
            "P003→C003、P007→C007 "
            f"{'均命中' if old_name_ok else '未均命中'}",
            {
                "P003": resolved_by_source.get("P003"),
                "P007": resolved_by_source.get("P007"),
            },
        )
    )

    # 7. Missing-code mention must stay in review (P008).
    review_by_source = {
        item["source_id"]: item for item in matching["review_mentions"]
    }
    p008_review = review_by_source.get("P008")
    p008_ok = bool(p008_review) and "missing_credit_code" in p008_review.get("conflicts", [])
    checks.append(
        _check(
            "缺失代码实体保守处理",
            PASS if p008_ok else FAIL,
            "P008（云岭新能源（深圳）有限公司）进入人工复核"
            if p008_ok else "P008 未按缺失信用代码规则进入复核",
            {"P008": p008_review},
        )
    )

    # 8. Hard conflict safety: no auto merge across differing non-empty codes.
    unsafe: list[dict[str, Any]] = []
    for candidate in matching["mention_matches"]:
        if candidate["decision"] != "auto_merge":
            continue
        left_code = normalize_credit_code(candidate["left_credit_code"])
        right_code = normalize_credit_code(candidate["right_credit_code"])
        if left_code and right_code and left_code != right_code:
            unsafe.append(candidate)
    checks.append(
        _check(
            "代码冲突硬闸门",
            PASS if not unsafe else FAIL,
            "不存在跨不同信用代码的自动合并"
            if not unsafe else f"发现 {len(unsafe)} 条越权自动合并",
            {"unsafe_candidates": [item["candidate_id"] for item in unsafe]},
        )
    )

    # 9. Canonical company count and no lost companies.
    canonical_ids = {str(item["company_id"]) for item in matching["canonical_companies"]}
    expected_canonical = int(expected_counts.get("companies", 8)) - len(variant_aliases)
    canonical_ok = len(canonical_ids) == expected_canonical
    checks.append(
        _check(
            "规范化企业数量",
            PASS if canonical_ok else FAIL,
            f"规范化企业 {len(canonical_ids)} 家（预期 {expected_canonical}）",
            {"canonical_ids": sorted(canonical_ids)},
        )
    )

    # 10. Shareholding percentages per canonical company.
    resolved_targets = {
        item["mention_id"]: item["company_id"] for item in matching["resolved_mentions"]
    }
    percentage_by_company: dict[str, float] = {}
    for fact in pipeline["entities"]["relationships"]["shareholding"]:
        company_id = resolved_targets.get(fact["target_mention_id"])
        if not company_id:
            continue
        percentage_by_company[company_id] = round(
            percentage_by_company.get(company_id, 0.0) + float(fact["percentage"]), 4
        )
    over_limit = {
        company_id: value
        for company_id, value in percentage_by_company.items()
        if value > 100.0 + tolerance
    }
    checks.append(
        _check(
            "股权比例合计",
            PASS if not over_limit else FAIL,
            f"已核对 {len(percentage_by_company)} 家企业，均不超过 100%"
            if not over_limit else f"超限企业：{over_limit}",
            {"percentage_by_company": percentage_by_company, "over_limit": over_limit},
        )
    )

    # 11. Offline graph seed integrity.
    label_keys = {
        "Company": "company_id",
        "CompanyAlias": "alias_id",
        "Person": "person_id",
        "ExternalOrganization": "organization_id",
        "Patent": "patent_id",
        "Region": "region_code",
        "MergeCandidate": "candidate_id",
    }
    node_keys = {
        label: {str(node["key_value"]) for node in seed["nodes"].get(label, [])}
        for label in label_keys
    }
    missing_endpoints: list[dict[str, Any]] = []
    for rel in seed["relationships"]:
        if rel["from_key"] not in node_keys.get(rel["from_label"], set()):
            missing_endpoints.append({"relationship": rel["type"], "missing": rel["from_key"]})
        if rel["to_key"] not in node_keys.get(rel["to_label"], set()):
            missing_endpoints.append({"relationship": rel["type"], "missing": rel["to_key"]})

    graph_ok = (
        len(node_keys["Company"]) == len(canonical_ids)
        and len(node_keys["Patent"]) == int(expected_counts.get("patents", 8))
        and len(node_keys["Region"]) == int(expected_counts.get("regions", 3))
        and not missing_endpoints
        and seed["meta"]["relationship_counts"].get("OWNS_PATENT", 0) >= 1
        and seed["meta"]["relationship_counts"].get("HOLDS_SHARES", 0) == 10
    )
    checks.append(
        _check(
            "离线图谱种子完整性",
            PASS if graph_ok else FAIL,
            f"Company={len(node_keys['Company'])}, Patent={len(node_keys['Patent'])}, "
            f"关系={seed['meta']['relationship_counts']}, 悬空端点={len(missing_endpoints)}",
            {
                "node_counts": seed["meta"]["node_counts"],
                "relationship_counts": seed["meta"]["relationship_counts"],
                "missing_endpoints": missing_endpoints,
            },
        )
    )

    # 12. Optional online Neo4j verification.
    if check_neo4j:
        neo4j_result = _neo4j_check(config, len(canonical_ids))
        if require_neo4j and neo4j_result["status"] == WARN:
            neo4j_result["status"] = FAIL
            neo4j_result["detail"] = "要求在线校验，但 " + neo4j_result["detail"]
        checks.append(neo4j_result)

    failures = [item for item in checks if item["status"] == FAIL]
    warnings = [item for item in checks if item["status"] == WARN]
    overall = "FAIL" if failures else ("PASS_WITH_WARNINGS" if warnings else PASS)

    report = {
        "generated_at": now_iso(),
        "overall_status": overall,
        "summary": {
            "total": len(checks),
            "pass": sum(item["status"] == PASS for item in checks),
            "warn": len(warnings),
            "fail": len(failures),
        },
        "checks": checks,
        "suspected_unmerged_pairs": matching["company_pairs"],
        "matching_stats": matching["stats"],
        "seed_path": str(seed_path),
        "ownership_percentages": percentage_by_company,
    }

    output_dir = project_path(config, "output_dir")
    report_path = output_dir / "quality_report.json"
    if write_report:
        json_dump(report_path, report)
        report["report_path"] = str(report_path)
    else:
        report["report_path"] = None
    return report


def _print_report(report: dict[str, Any]) -> None:
    print("=" * 78)
    print("EnterpriseKG 数据质量检查")
    print("=" * 78)
    for check in report["checks"]:
        print(f"[{check['status']:<4}] {check['name']}: {check['detail']}")
    print("-" * 78)
    summary = report["summary"]
    print(
        f"结果: {report['overall_status']} | PASS={summary['pass']} "
        f"WARN={summary['warn']} FAIL={summary['fail']}"
    )
    pairs = report["suspected_unmerged_pairs"]
    print(f"\n疑似未合并候选对（{len(pairs)} 对）:")
    if pairs:
        rows = [
            {
                "企业A": item["left_name"],
                "代码A": item["left_credit_code"] or "(缺失)",
                "企业B": item["right_name"],
                "代码B": item["right_credit_code"] or "(缺失)",
                "相似度": f"{item['score']:.2f}",
                "置信分层": item["confidence_tier"],
                "决策": item["decision"],
                "冲突": ",".join(item.get("conflicts", [])),
            }
            for item in pairs
        ]
        print(pd.DataFrame(rows).to_string(index=False))
    else:
        print("(none)")
    print(f"\n详细报告: {report['report_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run EnterpriseKG quality checks.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    parser.add_argument("--offline", action="store_true", help="Skip the online Neo4j check")
    parser.add_argument("--require-neo4j", action="store_true", help="Fail when Neo4j is unavailable")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    report = run_quality_checks(
        config,
        check_neo4j=not args.offline,
        require_neo4j=args.require_neo4j,
    )
    _print_report(report)
    return 0 if report["overall_status"] != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
