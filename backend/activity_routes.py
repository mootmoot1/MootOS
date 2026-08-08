"""Read-only activity/log routes for the MootOS interface.

This module adds no new storage and no new privacy surface. It exposes the
existing, already-tested ``backend.runs.list_runs`` execution/audit records
over HTTP for the first time, behind the same authenticated boundary as every
other private route. Run rows already exclude prompt/response content and raw
provider errors (see ``docs/MODEL_RUN_LOGGING.md`` and ``tests/test_runs.py``);
this route does not change that contract, only reads it.
"""

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.runs import list_runs


router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/runs")
def list_recent_runs(
    conversation_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return recent model-run execution metadata, newest first."""
    try:
        runs = list_runs(conversation_id=conversation_id, limit=limit)
    except sqlite3.Error as error:
        raise HTTPException(
            status_code=503,
            detail="MootOS could not load recent activity.",
        ) from error
    return {"success": True, "data": runs}
