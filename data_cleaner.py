"""Normalize raw records and attach row-level quality flags."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .config import CONFIG, load_config, project_path
from .data_loader import load_all
from .models import DataBundle
from .utils import (
    flags_to_text,
    is_valid_credit_code,
    json_dump,
    normalize_credit_code,
    normalize_name,
    now_iso,
)


def _valid_date(value: Any) -> tuple[str, bool]:
    text = str(value or "").strip()
    if not text:
        return "", False
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text, False
    return parsed.strftime("%Y-%m-%d"), True


def _number(value: Any) -> float:
    parsed = pd.to_numeric(str(value or "").replace(",", ""), errors="coerce")
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def clean_companies(frame: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["name"] = output["name"].astype(str).str.strip()
    output["normalized_name"] = output["name"].map(normalize_name)
    output["credit_code"] = output["credit_code"].map(normalize_credit_code)
    output["old_name"] = output["old_name"].astype(str).str.strip()
    output["normalized_old_name"] = output["old_name"].map(normalize_name)
    output["credit_code_missing"] = output["credit_code"].eq("")
    output["credit_code_valid"] = output["credit_code"].map(
        lambda value: is_valid_credit_code(value) if value else False
    )

    duplicate_counts = output.loc[output["credit_code"] != "", "credit_code"].value_counts()
    output["credit_code_duplicate_count"] = output["credit_code"].map(
        lambda value: int(duplicate_counts.get(value, 0)) if value else 0
    )

    output["registered_capital"] = output["registered_capital"].map(_number)
    dates = output["established_date"].map(_valid_date)
    output["established_date"] = [item[0] for item in dates]
    output["date_valid"] = [item[1] for item in dates]

    region_codes = set(regions["region_code"].astype(str))
    output["region_exists"] = output["region_code"].map(lambda value: value in region_codes)

    flags: list[list[str]] = []
    for _, row in output.iterrows():
        row_flags: list[str] = []
        if row["credit_code_missing"]:
            row_flags.append("missing_credit_code")
        elif not row["credit_code_valid"]:
            row_flags.append("invalid_credit_code")
        if row["credit_code_duplicate_count"] > 1:
            row_flags.append("duplicate_credit_code")
        if not row["date_valid"]:
            row_flags.append("invalid_established_date")
        if not row["region_exists"]:
            row_flags.append("unknown_region")
        if row["registered_capital"] <= 0:
            row_flags.append("missing_registered_capital")
        flags.append(row_flags)
    output["quality_flags"] = flags
    return output


def clean_shareholders(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["company_name"] = output["company_name"].astype(str).str.strip()
    output["normalized_company_name"] = output["company_name"].map(normalize_name)
    output["shareholder_name"] = output["shareholder_name"].astype(str).str.strip()
    output["normalized_shareholder_name"] = output["shareholder_name"].map(normalize_name)
    output["shareholder_type"] = (
        output["shareholder_type"].astype(str).str.strip().str.lower()
    )
    output["shareholder_credit_code"] = output["shareholder_credit_code"].map(
        normalize_credit_code
    )

    inferred = output["shareholder_type"].eq("")
    output.loc[inferred, "shareholder_type"] = output.loc[inferred].apply(
        lambda row: "enterprise" if row["shareholder_credit_code"] else "natural_person",
        axis=1,
    )
    output["ownership_percentage"] = output["ownership_percentage"].map(_number)
    output["investment_amount"] = output["investment_amount"].map(_number)

    dates = output["investment_date"].map(_valid_date)
    output["investment_date"] = [item[0] for item in dates]
    output["date_valid"] = [item[1] for item in dates]

    flags: list[list[str]] = []
    for _, row in output.iterrows():
        row_flags: list[str] = []
        if row["shareholder_type"] not in {"natural_person", "enterprise"}:
            row_flags.append("unknown_shareholder_type")
        if row["ownership_percentage"] <= 0 or row["ownership_percentage"] > 100:
            row_flags.append("percentage_out_of_range")
        if not row["date_valid"]:
            row_flags.append("invalid_investment_date")
        if row["shareholder_type"] == "enterprise" and not row["shareholder_credit_code"]:
            row_flags.append("missing_shareholder_credit_code")
        flags.append(row_flags)
    output["quality_flags"] = flags
    return output


def clean_patents(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["patent_name"] = output["patent_name"].astype(str).str.strip()
    output["patent_number"] = output["patent_number"].astype(str).str.strip()
    output["applicant_name"] = output["applicant_name"].astype(str).str.strip()
    output["normalized_applicant_name"] = output["applicant_name"].map(normalize_name)

    dates = output["application_date"].map(_valid_date)
    output["application_date"] = [item[0] for item in dates]
    output["date_valid"] = [item[1] for item in dates]

    flags: list[list[str]] = []
    for _, row in output.iterrows():
        row_flags: list[str] = []
        if not row["date_valid"]:
            row_flags.append("invalid_application_date")
        if not row["patent_number"]:
            row_flags.append("missing_patent_number")
        flags.append(row_flags)
    output["quality_flags"] = flags
    return output


def clean_regions(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in ("region_code", "province", "city", "district"):
        output[column] = output[column].astype(str).str.strip()
    output["region_label"] = (
        output["province"] + " / " + output["city"] + " / " + output["district"]
    )
    return output


def clean_all(bundle: DataBundle) -> DataBundle:
    regions = clean_regions(bundle.regions)
    companies = clean_companies(bundle.companies, regions)
    shareholders = clean_shareholders(bundle.shareholders)
    patents = clean_patents(bundle.patents)

    known_company_names = set(companies["normalized_name"])
    shareholder_flags: list[list[str]] = []
    for flags, company_name in zip(
        shareholders["quality_flags"], shareholders["normalized_company_name"]
    ):
        row_flags = list(flags)
        if company_name not in known_company_names:
            row_flags.append("unknown_investee_company")
        shareholder_flags.append(row_flags)
    shareholders["quality_flags"] = shareholder_flags

    return DataBundle(
        companies=companies,
        shareholders=shareholders,
        patents=patents,
        regions=regions,
    )


def _frame_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output.columns:
        if output[column].map(lambda value: isinstance(value, list)).any():
            output[column] = output[column].map(flags_to_text)
    return output


def write_clean_artifacts(bundle: DataBundle, config: dict | None = None) -> dict[str, str]:
    config = config or CONFIG
    output_dir = project_path(config, "processed_dir")
    paths: dict[str, str] = {}
    for name, frame in bundle.as_dict().items():
        path = output_dir / f"{name}_clean.csv"
        _frame_for_csv(frame).to_csv(path, index=False, encoding="utf-8-sig")
        paths[name] = str(path)

    summary = {
        "generated_at": now_iso(),
        "counts": bundle.summary(),
        "flags": {
            name: int(
                frame["quality_flags"].map(bool).sum()
                if "quality_flags" in frame.columns
                else 0
            )
            for name, frame in bundle.as_dict().items()
        },
        "files": paths,
    }
    summary_path = output_dir / "clean_summary.json"
    json_dump(summary_path, summary)
    paths["summary"] = str(summary_path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean EnterpriseKG raw CSV tables.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    parser.add_argument("--no-write", action="store_true", help="Do not write processed CSVs")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    clean = clean_all(load_all(config))
    paths = {} if args.no_write else write_clean_artifacts(clean, config)
    payload = {
        "status": "ok",
        "counts": clean.summary(),
        "flagged_rows": {
            name: int(
                frame["quality_flags"].map(bool).sum()
                if "quality_flags" in frame.columns
                else 0
            )
            for name, frame in clean.as_dict().items()
        },
        "written": paths,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
