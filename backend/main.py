"""FastAPI application for MootOS."""

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from backend.memory import (
    create_memory as store_memory,
    delete_memory as remove_memory,
    get_memory as load_memory,
    init_db,
    list_memories as load_memories,
)


app = FastAPI(
    title="MootOS",
    description="The backend foundation for MootOS.",
    version="0.1.0",
)
init_db()


class MemoryCreate(BaseModel):
    """Input accepted when creating a memory."""

    content: str = Field(min_length=1, max_length=10_000)
    project: Optional[str] = None
    memory_type: Optional[str] = None


@app.get("/")
def home() -> dict[str, str]:
    """Return the basic MootOS status."""
    return {
        "name": "MootOS",
        "version": "0.1.0",
        "status": "Backend Running",
        "message": "Welcome to MootOS.",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return a simple health check for the application."""
    return {"status": "healthy"}


@app.post("/memories", status_code=status.HTTP_201_CREATED)
def create_memory(memory: MemoryCreate) -> dict[str, Any]:
    """Create and persist a memory."""
    return {
        "success": True,
        "data": store_memory(
            content=memory.content,
            project=memory.project,
            memory_type=memory.memory_type,
        ),
    }


@app.get("/memories")
def list_memories() -> dict[str, Any]:
    """List all saved memories."""
    return {"success": True, "data": load_memories()}


@app.get("/memories/{memory_id}")
def get_memory(memory_id: str) -> dict[str, Any]:
    """Retrieve a saved memory by ID."""
    memory = load_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "data": memory}


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete a saved memory by ID."""
    if not remove_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"success": True, "data": {"id": memory_id, "status": "deleted"}}
