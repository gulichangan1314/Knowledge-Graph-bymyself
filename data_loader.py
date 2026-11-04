"""Load and validate the four raw CSV tables."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import CONFIG, load_config, project_path
from .models import DataBundle

SCHEMAS: dict[str, list[str]] = {
    "companies": [
        "company_id",
        "name",
        "credit_code",
        "legal_representative",
        "registered_capital",
        "established_date",
        "region_code",
        "industry",
        "status",
        "old_name",
    ],
    "shareholders": [
        "shareholder_id",
        "company_name",
        "shareholder_name",
        "shareholder_type",
        "shareholder_credit_code",
        "ownership_percentage",
        "investment_amount",
        "investment_date",
    ],
    "patents": [
        "patent_id",
        "patent_name",
        "patent_number",
        "application_date",
        "applicant_name",
        "patent_type",
        "status",
    ],
    "regions": ["region_code", "province", "city", "district"],
}


class DataContractError(ValueError):
    """Raised when a raw table violates its agreed schema."""


def _read_table(path: Path, required: list[str]) -> pd.DataFrame:
    if not path.is_file():
        raise DataContractError(f"Missing raw data file: {path}")

    frame = pd.read_csv(
        path,
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False,
        na_values=[],
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DataContractError(f"{path.name}: missing columns {missing}")

    for column in frame.columns:
        frame[column] = frame[column].fillna("").astype(str).str.strip()

    frame["source_file"] = path.name
    return frame


def load_all(config: dict | None = None) -> DataBundle:
    config = config or CONFIG
    raw_dir = project_path(config, "raw_dir")
    files = config.get("files", {})

    frames: dict[str, pd.DataFrame] = {}
    for table, required in SCHEMAS.items():
        filename = files.get(table)
        if not filename:
            raise DataContractError(f"files.{table} is not configured")
        frames[table] = _read_table(raw_dir / filename, required)

    bundle = DataBundle(**frames)
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: DataBundle) -> None:
    """Structural checks that should fail before any cleaning happens."""
    for table, required in SCHEMAS.items():
        frame = bundle.as_dict()[table]
        if frame.empty:
            raise DataContractError(f"{table}: table is empty")
        for column in required:
            if frame[column].isna().any():
                raise DataContractError(f"{table}.{column}: unexpected null values")

    company_ids = bundle.companies["company_id"]
    if company_ids.duplicated().any():
        duplicates = sorted(company_ids[company_ids.duplicated()].unique().tolist())
        raise DataContractError(f"companies.company_id duplicated: {duplicates}")

    region_ids = bundle.regions["region_code"]
    if region_ids.duplicated().any():
        duplicates = sorted(region_ids[region_ids.duplicated()].unique().tolist())
        raise DataContractError(f"regions.region_code duplicated: {duplicates}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load and validate EnterpriseKG raw CSVs.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    bundle = load_all(config)
    payload = {
        "status": "ok",
        "counts": bundle.summary(),
        "tables": {
            name: {
                "columns": list(frame.columns),
                "rows": int(len(frame)),
            }
            for name, frame in bundle.as_dict().items()
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
