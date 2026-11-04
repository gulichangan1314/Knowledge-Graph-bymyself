"""Entity alignment with rapidfuzz plus hard credit-code conflict rules.

Design rule: similarity is *evidence*, not permission. A high name score never
overrides two different non-empty Unified Social Credit Codes. Missing codes are
capped at manual review. Only same-code variants and trusted aliases auto-merge.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from rapidfuzz import __version__ as RAPIDFUZZ_VERSION
    from rapidfuzz import fuzz as rapidfuzz_fuzz

    RAPIDFUZZ_AVAILABLE = True
    MATCH_ENGINE = f"rapidfuzz {RAPIDFUZZ_VERSION}"
except ImportError:  # pragma: no cover - only used when deps are missing
    rapidfuzz_fuzz = None
    RAPIDFUZZ_VERSION = None
    RAPIDFUZZ_AVAILABLE = False
    MATCH_ENGINE = "difflib fallback (rapidfuzz is not installed)"

from .config import CONFIG, load_config, project_path
from .data_cleaner import clean_all
from .data_loader import load_all
from .entity_extractor import extract_entities
from .models import MatchCandidate
from .utils import json_dump, normalize_credit_code, now_iso, stable_id


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if RAPIDFUZZ_AVAILABLE:
        return float(rapidfuzz_fuzz.WRatio(left, right))
    return float(SequenceMatcher(None, left, right).ratio() * 100.0)


def _tier(score: float, config: dict[str, Any]) -> str:
    matching = config["matching"]
    if score >= float(matching.get("confidence_high_threshold", 88)):
        return "high"
    if score >= float(matching.get("confidence_medium_threshold", 78)):
        return "medium"
    return "low"


def _canonicalize_companies(
    companies: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge only same-credit-code rows; collect registered old names as aliases."""
    by_code: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    no_code: list[dict[str, Any]] = []

    for company in companies:
        credit_code = normalize_credit_code(company.get("credit_code", ""))
        if credit_code:
            by_code.setdefault(credit_code, []).append(company)
        else:
            no_code.append(company)

    canonical: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    alias_keys: set[tuple[str, str, str]] = set()

    def add_alias(
        primary: dict[str, Any],
        *,
        name: str,
        normalized_name: str,
        alias_type: str,
        source_company_id: str,
        credit_code: str,
        confidence: float,
        method: str,
    ) -> None:
        key = (normalized_name, alias_type, source_company_id)
        if not normalized_name or key in alias_keys:
            return
        alias_keys.add(key)
        record = {
            "alias_id": stable_id("ALIAS", primary["company_id"], alias_type, normalized_name),
            "canonical_company_id": primary["company_id"],
            "canonical_name": primary["name"],
            "name": name,
            "normalized_name": normalized_name,
            "alias_type": alias_type,
            "source_company_id": source_company_id,
            "credit_code": credit_code,
            "confidence": confidence,
            "method": method,
            "decision": "auto_merge",
        }
        primary["aliases"].append(record)
        primary["alias_names"].append(name)
        aliases.append(record)

    for credit_code, group in by_code.items():
        group_sorted = sorted(group, key=lambda row: str(row["company_id"]))
        primary = dict(group_sorted[0])
        primary["credit_code"] = credit_code
        primary["aliases"] = []
        primary["alias_names"] = []
        primary["source_company_ids"] = [str(row["company_id"]) for row in group_sorted]
        primary["merged_variant_count"] = len(group_sorted) - 1
        primary["is_canonical"] = True
        flags: set[str] = set()

        for member in group_sorted:
            flags.update(member.get("quality_flags", []))
            old_name = str(member.get("old_name", "") or "").strip()
            old_norm = str(member.get("normalized_old_name", "") or "")
            if old_name and old_norm:
                add_alias(
                    primary,
                    name=old_name,
                    normalized_name=old_norm,
                    alias_type="old_name",
                    source_company_id=str(member["company_id"]),
                    credit_code=credit_code,
                    confidence=98.0,
                    method="registered_old_name",
                )
            if str(member["company_id"]) != primary["company_id"]:
                add_alias(
                    primary,
                    name=str(member["name"]),
                    normalized_name=str(member["normalized_name"]),
                    alias_type="same_code_variant",
                    source_company_id=str(member["company_id"]),
                    credit_code=credit_code,
                    confidence=100.0,
                    method="same_credit_code",
                )

        primary["quality_flags"] = sorted(flags)
        primary["credit_code_missing"] = False
        primary["credit_code_duplicate_count"] = len(group_sorted)
        canonical.append(primary)

    for company in no_code:
        primary = dict(company)
        primary["aliases"] = []
        primary["alias_names"] = []
        primary["source_company_ids"] = [str(company["company_id"])]
        primary["merged_variant_count"] = 0
        primary["is_canonical"] = True
        primary["credit_code"] = ""
        primary["credit_code_missing"] = True
        old_name = str(company.get("old_name", "") or "").strip()
        old_norm = str(company.get("normalized_old_name", "") or "")
        if old_name and old_norm:
            add_alias(
                primary,
                name=old_name,
                normalized_name=old_norm,
                alias_type="old_name",
                source_company_id=str(company["company_id"]),
                credit_code="",
                confidence=90.0,
                method="registered_old_name_no_code",
            )
        canonical.append(primary)

    return canonical, aliases


def _build_indexes(
    canonical: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    code_index: dict[str, str] = {}
    name_index: dict[str, list[str]] = {}
    old_name_index: dict[str, list[str]] = {}

    def add(index: dict[str, list[str]], key: str, company_id: str) -> None:
        if not key:
            return
        bucket = index.setdefault(key, [])
        if company_id not in bucket:
            bucket.append(company_id)

    for company in canonical:
        company_id = str(company["company_id"])
        credit_code = normalize_credit_code(company.get("credit_code", ""))
        if credit_code:
            code_index[credit_code] = company_id
        add(name_index, str(company.get("normalized_name", "")), company_id)

    for alias in aliases:
        company_id = str(alias["canonical_company_id"])
        add(name_index, str(alias["normalized_name"]), company_id)
        if alias["alias_type"] == "old_name":
            add(old_name_index, str(alias["normalized_name"]), company_id)

    return code_index, name_index, old_name_index


def _company_similarity(
    left: dict[str, Any],
    right: dict[str, Any],
    config: dict[str, Any],
) -> tuple[float, float, float]:
    matching = config["matching"]
    name_score = _ratio(str(left["normalized_name"]), str(right["normalized_name"]))
    region_score = 100.0 if left.get("region_code") == right.get("region_code") else 0.0
    industry_score = 100.0 if left.get("industry") == right.get("industry") else 0.0
    legal_left = str(left.get("legal_representative", "") or "")
    legal_right = str(right.get("legal_representative", "") or "")
    if legal_left and legal_right:
        legal_score = 100.0 if legal_left == legal_right else 0.0
    else:
        legal_score = 50.0

    region_weight = float(matching.get("region_weight", 0.12))
    industry_weight = float(matching.get("industry_weight", 0.08))
    legal_weight = float(matching.get("legal_rep_weight", 0.08))
    context_weight = region_weight + industry_weight + legal_weight
    context_score = (
        (region_score * region_weight
         + industry_score * industry_weight
         + legal_score * legal_weight)
        / context_weight
        if context_weight
        else 50.0
    )
    name_weight = float(matching.get("name_weight", 0.72))
    composite = name_weight * name_score + context_weight * context_score
    return name_score, context_score, composite


def _compare_company_pairs(
    canonical: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    matching = config["matching"]
    pair_min = float(matching.get("company_pair_min_score", 78))
    review = float(matching.get("review_threshold", 78))
    candidates: list[dict[str, Any]] = []

    for index, left in enumerate(canonical):
        for right in canonical[index + 1:]:
            name_score, context_score, score = _company_similarity(left, right, config)
            if score < min(pair_min, review) or name_score < 70:
                continue

            left_code = normalize_credit_code(left.get("credit_code", ""))
            right_code = normalize_credit_code(right.get("credit_code", ""))
            conflicts: list[str] = []
            reasons: list[str] = []
            if left_code and right_code and left_code != right_code:
                conflicts.append("different_credit_code")
                reasons.append(
                    f"统一社会信用代码不一致（{left_code} ≠ {right_code}），禁止自动合并"
                )
                if name_score >= 95:
                    conflicts.append("name_collision")
                    reasons.append("名称高度相同但信用代码不同，属于高风险同名/近名实体")
            elif not left_code or not right_code:
                conflicts.append("missing_credit_code")
                reasons.append("一方缺失统一社会信用代码，最高只能进入人工复核")
            else:
                conflicts.append("same_credit_code_not_merged")
                reasons.append("同一信用代码未被归并，需检查归并逻辑")

            if (
                str(left.get("legal_representative", "") or "")
                and str(left.get("legal_representative", "") or "")
                == str(right.get("legal_representative", "") or "")
            ):
                reasons.append("法定代表人也相同，需要排查母子公司或重复登记")
            if left.get("region_code") == right.get("region_code"):
                reasons.append("登记地区一致")
            if left.get("industry") == right.get("industry"):
                reasons.append("行业一致")

            candidate = MatchCandidate(
                candidate_id=f"PAIR-{left['company_id']}-{right['company_id']}",
                candidate_type="company_pair",
                left_id=str(left["company_id"]),
                left_name=str(left["name"]),
                left_credit_code=left_code,
                right_id=str(right["company_id"]),
                right_name=str(right["name"]),
                right_credit_code=right_code,
                name_score=name_score,
                context_score=context_score,
                score=score,
                confidence_tier=_tier(score, config),
                decision="review",
                method="context_weighted_rapidfuzz",
                conflicts=conflicts,
                reasons=reasons,
                source_type="company_record",
                source_id=f"{left['company_id']}|{right['company_id']}",
            )
            candidates.append(candidate.to_dict())

    candidates.sort(key=lambda item: (-item["score"], item["candidate_id"]))
    return candidates


def _conflict_for_target(
    source_credit_code: str,
    target: dict[str, Any],
) -> tuple[list[str], list[str]]:
    target_code = normalize_credit_code(target.get("credit_code", ""))
    if source_credit_code and target_code and source_credit_code != target_code:
        return (
            ["different_credit_code"],
            [f"来源信用代码 {source_credit_code} 与目标 {target_code} 冲突，禁止自动合并"],
        )
    if not target_code:
        return (
            ["missing_credit_code"],
            ["目标企业缺失统一社会信用代码，只能进入人工复核"],
        )
    return [], []


def _match_mentions(
    mentions: list[dict[str, Any]],
    canonical: list[dict[str, Any]],
    code_index: dict[str, str],
    name_index: dict[str, list[str]],
    old_name_index: dict[str, list[str]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    matching = config["matching"]
    auto_threshold = float(matching.get("auto_merge_threshold", 92))
    review_threshold = float(matching.get("review_threshold", 78))
    by_id = {str(company["company_id"]): company for company in canonical}

    candidates: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for mention in mentions:
        source_code = normalize_credit_code(mention.get("credit_code", ""))
        name_norm = str(mention.get("normalized_name", ""))
        target: dict[str, Any] | None = None
        method = ""
        score = 0.0
        conflicts: list[str] = []
        reasons: list[str] = []

        if source_code and source_code in code_index:
            target = by_id[code_index[source_code]]
            score = 100.0
            method = "credit_code"
            reasons.append("来源侧信用代码与目标企业完全一致")
        else:
            exact_ids = name_index.get(name_norm, [])
            if len(exact_ids) == 1:
                target = by_id[exact_ids[0]]
                score = 98.0
                if name_norm in old_name_index and target["company_id"] in old_name_index[name_norm]:
                    method = "registered_old_name"
                    reasons.append("命中企业登记过的曾用名")
                else:
                    is_variant = any(
                        alias["normalized_name"] == name_norm
                        and alias["alias_type"] == "same_code_variant"
                        for alias in target.get("aliases", [])
                    )
                    method = "same_code_variant" if is_variant else "exact_name"
                    reasons.append(
                        "命中同一信用代码下的名称变体" if is_variant else "企业名称标准化后完全一致"
                    )
                conflicts, conflict_reasons = _conflict_for_target(source_code, target)
                reasons.extend(conflict_reasons)
            elif len(exact_ids) > 1:
                target = by_id[exact_ids[0]]
                score = 100.0
                method = "exact_name_ambiguous"
                conflicts = ["ambiguous_name"]
                reasons.append("多个企业命中同一名称，禁止自动合并，转人工消歧")
            else:
                ranked = sorted(
                    (
                        (_ratio(name_norm, str(company["normalized_name"])), str(company["company_id"]))
                        for company in canonical
                    ),
                    reverse=True,
                )
                if ranked and ranked[0][0] >= review_threshold:
                    score = ranked[0][0]
                    target = by_id[ranked[0][1]]
                    method = "fuzzy_name"
                    reasons.append(f"rapidfuzz 名称相似度 {score:.2f}")
                    conflicts, conflict_reasons = _conflict_for_target(source_code, target)
                    reasons.extend(conflict_reasons)
                else:
                    unresolved.append(
                        {
                            "mention_id": mention["mention_id"],
                            "source_type": mention["source_type"],
                            "source_id": mention["source_id"],
                            "name": mention["name"],
                            "best_score": round(ranked[0][0], 2) if ranked else 0.0,
                        }
                    )
                    continue

        assert target is not None
        target_code = normalize_credit_code(target.get("credit_code", ""))
        if "different_credit_code" in conflicts or "ambiguous_name" in conflicts:
            decision = "review"
            tier = _tier(score, config)
        elif "missing_credit_code" in conflicts:
            decision = "review"
            score = min(score, auto_threshold - 0.1)
            tier = _tier(score, config)
        elif method in {"credit_code", "same_code_variant", "registered_old_name", "exact_name"}:
            decision = "auto_merge"
            tier = "high"
        elif score >= auto_threshold:
            decision = "auto_merge"
            tier = "high"
        else:
            decision = "review"
            tier = _tier(score, config)

        candidate = MatchCandidate(
            candidate_id=f"MM-{mention['mention_id']}",
            candidate_type="mention",
            left_id=str(mention["mention_id"]),
            left_name=str(mention["name"]),
            left_credit_code=source_code,
            right_id=str(target["company_id"]),
            right_name=str(target["name"]),
            right_credit_code=target_code,
            name_score=score,
            context_score=100.0 if source_code else 0.0,
            score=score,
            confidence_tier=tier,
            decision=decision,
            method=method,
            conflicts=conflicts,
            reasons=reasons,
            source_type=str(mention["source_type"]),
            source_id=str(mention["source_id"]),
            canonical_id=str(target["company_id"]),
        ).to_dict()
        candidates.append(candidate)

        resolved_item = {
            "mention_id": mention["mention_id"],
            "source_type": mention["source_type"],
            "source_id": mention["source_id"],
            "name": mention["name"],
            "company_id": target["company_id"],
            "company_name": target["name"],
            "score": round(score, 2),
            "method": method,
        }
        if decision == "auto_merge":
            resolved.append(resolved_item)
        else:
            review.append({**resolved_item, "conflicts": conflicts, "reasons": reasons})

    return candidates, resolved, review, unresolved


def match_entities(entities: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or CONFIG
    canonical, aliases = _canonicalize_companies(entities["companies"])
    code_index, name_index, old_name_index = _build_indexes(canonical, aliases)

    company_pairs = _compare_company_pairs(canonical, config)
    mention_matches, resolved, review_mentions, unresolved = _match_mentions(
        entities["mentions"],
        canonical,
        code_index,
        name_index,
        old_name_index,
        config,
    )

    auto_mentions = [item for item in mention_matches if item["decision"] == "auto_merge"]
    distinct_credit_groups = len(
        {
            normalize_credit_code(company.get("credit_code", ""))
            for company in entities["companies"]
            if normalize_credit_code(company.get("credit_code", ""))
        }
    )
    report = {
        "generated_at": now_iso(),
        "engine": MATCH_ENGINE,
        "rapidfuzz_version": RAPIDFUZZ_VERSION,
        "thresholds": {
            "auto_merge": config["matching"]["auto_merge_threshold"],
            "review": config["matching"]["review_threshold"],
            "confidence_high": config["matching"].get("confidence_high_threshold", 88),
            "confidence_medium": config["matching"].get("confidence_medium_threshold", 78),
        },
        "canonical_companies": canonical,
        "aliases": aliases,
        "company_pairs": company_pairs,
        "mention_matches": mention_matches,
        "resolved_mentions": resolved,
        "review_mentions": review_mentions,
        "unresolved_mentions": unresolved,
        "stats": {
            "raw_company_records": len(entities["companies"]),
            "canonical_companies": len(canonical),
            "merged_variant_records": len(entities["companies"]) - len(canonical),
            "distinct_credit_code_groups": distinct_credit_groups,
            "aliases": len(aliases),
            "suspicious_company_pairs": len(company_pairs),
            "auto_merged_mentions": len(auto_mentions),
            "review_mentions": len(review_mentions),
            "unresolved_mentions": len(unresolved),
        },
    }
    return report


def write_match_artifacts(report: dict[str, Any], config: dict | None = None) -> dict[str, str]:
    config = config or CONFIG
    output_dir = project_path(config, "processed_dir")
    report_path = output_dir / "match_report.json"
    json_dump(report_path, report)

    rows = list(report["company_pairs"]) + list(report["mention_matches"])
    for row in rows:
        row["conflicts_text"] = "；".join(row.get("conflicts", []))
        row["reasons_text"] = "；".join(row.get("reasons", []))
    csv_path = output_dir / "match_candidates.csv"
    if rows:
        pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    else:
        csv_path.write_text("candidate_id\n", encoding="utf-8")
    return {"report": str(report_path), "candidates": str(csv_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Align EnterpriseKG entities.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    entities = extract_entities(clean_all(load_all(config)))
    report = match_entities(entities, config)
    paths = write_match_artifacts(report, config)
    print(
        json.dumps(
            {
                "status": "ok",
                "engine": report["engine"],
                "stats": report["stats"],
                "top_suspicious_pairs": report["company_pairs"][:5],
                "written": paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
