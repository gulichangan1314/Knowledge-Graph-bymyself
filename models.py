"""Shared data structures used across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class DataBundle:
    """Four source tables kept together while flowing through the pipeline."""

    companies: pd.DataFrame
    shareholders: pd.DataFrame
    patents: pd.DataFrame
    regions: pd.DataFrame

    def as_dict(self) -> dict[str, pd.DataFrame]:
        return {
            "companies": self.companies,
            "shareholders": self.shareholders,
            "patents": self.patents,
            "regions": self.regions,
        }

    def summary(self) -> dict[str, int]:
        return {name: int(len(frame)) for name, frame in self.as_dict().items()}


@dataclass
class MatchCandidate:
    """One auditable alignment candidate.

    ``confidence_tier`` answers "how similar are they?".
    ``decision`` answers "are we allowed to merge them?".
    Keeping those separate is deliberate: a 100-point name match can still be
    a hard conflict when two different credit codes are present.
    """

    candidate_id: str
    candidate_type: str
    left_id: str
    left_name: str
    left_credit_code: str
    right_id: str
    right_name: str
    right_credit_code: str
    name_score: float
    context_score: float
    score: float
    confidence_tier: str
    decision: str
    method: str
    conflicts: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source_type: str = ""
    source_id: str = ""
    canonical_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "left_id": self.left_id,
            "left_name": self.left_name,
            "left_credit_code": self.left_credit_code,
            "right_id": self.right_id,
            "right_name": self.right_name,
            "right_credit_code": self.right_credit_code,
            "name_score": round(float(self.name_score), 2),
            "context_score": round(float(self.context_score), 2),
            "score": round(float(self.score), 2),
            "confidence_tier": self.confidence_tier,
            "decision": self.decision,
            "method": self.method,
            "conflicts": list(self.conflicts),
            "reasons": list(self.reasons),
            "source_type": self.source_type,
            "source_id": self.source_id,
            "canonical_id": self.canonical_id,
        }
