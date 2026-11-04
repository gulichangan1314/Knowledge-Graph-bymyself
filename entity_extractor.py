"""Extract graph-ready entities, mentions, and relationship facts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from typing import Any

from .config import CONFIG, load_config, project_path
from .data_loader import load_all
from .data_cleaner import clean_all
from .models import DataBundle
from .utils import json_dump, now_iso, row_to_dict, stable_id


def _aggregate_by_id(
    items: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    """Deduplicate holders/orgs while preserving every source row id."""
    grouped: dict[str, dict[str, Any]] = {}
    source_ids: dict[str, set[str]] = {}
    for item in items:
        item_id = str(item[key])
        if item_id not in grouped:
            grouped[item_id] = dict(item)
            source_ids[item_id] = set()
        source_ids[item_id].update(str(value) for value in item.get("source_ids", []))
    for item_id, item in grouped.items():
        item["source_ids"] = sorted(source_ids[item_id])
    return list(grouped.values())


def extract_entities(bundle: DataBundle) -> dict[str, Any]:
    regions = [row_to_dict(row) for row in bundle.regions.to_dict("records")]
    region_by_code = {row["region_code"]: row for row in regions}

    companies: list[dict[str, Any]] = []
    company_regions: list[dict[str, Any]] = []
    for row in bundle.companies.to_dict("records"):
        record = row_to_dict(row)
        region = region_by_code.get(record["region_code"], {})
        record["region_label"] = region.get("region_label", "")
        companies.append(record)
        company_regions.append(
            {
                "company_id": record["company_id"],
                "region_code": record["region_code"],
                "region_label": record.get("region_label", ""),
            }
        )

    patents = [row_to_dict(row) for row in bundle.patents.to_dict("records")]

    persons: list[dict[str, Any]] = []
    external_orgs: list[dict[str, Any]] = []
    shareholdings: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []

    for row in bundle.shareholders.to_dict("records"):
        record = row_to_dict(row)
        shareholder_id = record["shareholder_id"]
        holder_type = record["shareholder_type"]
        company_name = record["company_name"]

        target_mention_id = f"MSH-{shareholder_id}-TARGET"
        mentions.append(
            {
                "mention_id": target_mention_id,
                "source_type": "shareholder_target",
                "source_id": shareholder_id,
                "name": company_name,
                "normalized_name": record["normalized_company_name"],
                "credit_code": "",
                "context": {
                    "company_name": company_name,
                    "shareholder_name": record["shareholder_name"],
                    "ownership_percentage": record["ownership_percentage"],
                },
            }
        )

        if holder_type == "natural_person":
            person_id = stable_id("PER", record["normalized_shareholder_name"])
            persons.append(
                {
                    "person_id": person_id,
                    "name": record["shareholder_name"],
                    "normalized_name": record["normalized_shareholder_name"],
                    "source_ids": [shareholder_id],
                }
            )
            holder_id = person_id
            holder_label = "Person"
            holder_mention_id = ""
        else:
            organization_id = stable_id(
                "ORG",
                record["shareholder_credit_code"] or record["normalized_shareholder_name"],
            )
            external_orgs.append(
                {
                    "organization_id": organization_id,
                    "name": record["shareholder_name"],
                    "normalized_name": record["normalized_shareholder_name"],
                    "credit_code": record["shareholder_credit_code"],
                    "source_ids": [shareholder_id],
                }
            )
            holder_id = organization_id
            holder_label = "ExternalOrganization"
            holder_mention_id = f"MSH-{shareholder_id}-ORG"
            mentions.append(
                {
                    "mention_id": holder_mention_id,
                    "source_type": "shareholder_org",
                    "source_id": shareholder_id,
                    "name": record["shareholder_name"],
                    "normalized_name": record["normalized_shareholder_name"],
                    "credit_code": record["shareholder_credit_code"],
                    "context": {
                        "company_name": company_name,
                        "ownership_percentage": record["ownership_percentage"],
                    },
                }
            )

        shareholdings.append(
            {
                "shareholder_id": shareholder_id,
                "from_type": holder_type,
                "from_label": holder_label,
                "from_id": holder_id,
                "from_name": record["shareholder_name"],
                "to_company_name": company_name,
                "to_company_credit_code": "",
                "target_mention_id": target_mention_id,
                "holder_mention_id": holder_mention_id,
                "percentage": record["ownership_percentage"],
                "amount": record["investment_amount"],
                "date": record["investment_date"],
            }
        )

    patent_ownership: list[dict[str, Any]] = []
    for record in patents:
        mention_id = f"MPAT-{record['patent_id']}"
        mentions.append(
            {
                "mention_id": mention_id,
                "source_type": "patent_applicant",
                "source_id": record["patent_id"],
                "name": record["applicant_name"],
                "normalized_name": record["normalized_applicant_name"],
                "credit_code": "",
                "context": {
                    "patent_name": record["patent_name"],
                    "patent_number": record["patent_number"],
                    "application_date": record["application_date"],
                },
            }
        )
        patent_ownership.append(
            {
                "patent_id": record["patent_id"],
                "applicant_name": record["applicant_name"],
                "mention_id": mention_id,
                "application_date": record["application_date"],
            }
        )

    # Merge duplicate holders/orgs created by multiple shareholding records.
    persons = _aggregate_by_id(persons, "person_id")
    external_orgs = _aggregate_by_id(external_orgs, "organization_id")

    entities = {
        "generated_at": now_iso(),
        "companies": companies,
        "persons": persons,
        "external_organizations": external_orgs,
        "patents": patents,
        "regions": regions,
        "mentions": mentions,
        "relationships": {
            "shareholding": shareholdings,
            "patent_ownership": patent_ownership,
            "company_region": company_regions,
        },
        "stats": {
            "companies": len(companies),
            "persons": len(persons),
            "external_organizations": len(external_orgs),
            "patents": len(patents),
            "regions": len(regions),
            "mentions": len(mentions),
            "shareholding_facts": len(shareholdings),
            "patent_facts": len(patent_ownership),
        },
    }
    return entities


def write_entities(entities: dict[str, Any], config: dict | None = None) -> str:
    config = config or CONFIG
    output_dir = project_path(config, "processed_dir")
    path = output_dir / "entities.json"
    json_dump(path, entities)
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract EnterpriseKG entities and facts.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    entities = extract_entities(clean_all(load_all(config)))
    path = write_entities(entities, config)
    print(json.dumps({"status": "ok", "stats": entities["stats"], "written": path}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
