"""Pure history-summary projection shared by repository implementations."""

from app.schemas.orchestration import AnalysisJob
from app.schemas.persistence import HistoryItem


def history_item(job: AnalysisJob) -> HistoryItem:
    def score(method: str) -> float | None:
        execution = job.methods.get(method)
        return (
            execution.result.raw_score
            if execution is not None
            and execution.result is not None
            and hasattr(execution.result, "raw_score")
            else None
        )

    return HistoryItem(
        job_id=job.job_id,
        sequence_name=job.sequence.name,
        sequence_length=job.sequence.length,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
        status=job.status,
        selected_methods=job.selected_methods,
        prediction_mode=job.prediction_mode,
        lreca_score=score("lreca"),
        fuzdrop_score=score("fuzdrop"),
        ensemble_score=job.ensemble.score if job.ensemble else None,
        result_schema_version=job.result_schema_version,
    )
