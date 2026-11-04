"""One deterministic pipeline: load -> clean -> extract -> align -> persist."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import CONFIG, load_config, project_path
from .data_cleaner import clean_all, write_clean_artifacts
from .data_loader import load_all
from .entity_extractor import extract_entities
from .entity_matcher import match_entities, write_match_artifacts
from .models import DataBundle
from .utils import json_dump, now_iso


def _persist_entities(entities: dict[str, Any], config: dict[str, Any]) -> str:
    path = project_path(config, "processed_dir") / "entities.json"
    json_dump(path, entities)
    return str(path)


def run_pipeline(
    config: dict[str, Any] | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Run the full local pipeline and optionally persist audit artifacts."""
    config = config or CONFIG
    raw: DataBundle = load_all(config)
    clean: DataBundle = clean_all(raw)
    entities = extract_entities(clean)
    matching = match_entities(entities, config)

    written: dict[str, str] = {}
    if write:
        written.update(write_clean_artifacts(clean, config))
        written["entities"] = _persist_entities(entities, config)
        written.update(write_match_artifacts(matching, config))

        meta = {
            "generated_at": now_iso(),
            "project": config.get("project", {}).get("name", "EnterpriseKG"),
            "version": config.get("project", {}).get("version", "1.0.0"),
            "counts": {
                "raw": raw.summary(),
                "canonical_companies": len(matching["canonical_companies"]),
                "aliases": len(matching["aliases"]),
                "company_pairs": len(matching["company_pairs"]),
                "mention_matches": len(matching["mention_matches"]),
            },
            "match_engine": matching["engine"],
            "written": written,
        }
        meta_path = project_path(config, "processed_dir") / "pipeline_meta.json"
        json_dump(meta_path, meta)
        written["pipeline_meta"] = str(meta_path)

    return {
        "raw": raw,
        "clean": clean,
        "entities": entities,
        "matching": matching,
        "written": written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the EnterpriseKG local pipeline.")
    parser.add_argument("--config", help="Optional path to config.yaml")
    parser.add_argument("--no-write", action="store_true", help="Do not persist artifacts")
    args = parser.parse_args(argv)

    config = load_config(args.config) if args.config else CONFIG
    result = run_pipeline(config, write=not args.no_write)
    print(
        json.dumps(
            {
                "status": "ok",
                "counts": result["raw"].summary(),
                "match_engine": result["matching"]["engine"],
                "matching_stats": result["matching"]["stats"],
                "written": result["written"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
