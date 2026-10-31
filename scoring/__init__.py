"""Signal-to-sequence scoring engine. Rules: docs/scoring_specification.md (approved v3.1)."""

from .pipeline import SyntheticDataError, assess_record, score_file, sequencing_export

__all__ = ["SyntheticDataError", "assess_record", "score_file", "sequencing_export"]
