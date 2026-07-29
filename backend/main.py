"""FastAPI application for MootOS."""

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from backend.memory import (
    create_project as store_project,
    create_memory as store_memory,
    delete_memory as remove_memory,
    get_memory as load_memory,
    init_db,
    list_memories as load_memories,
    list_projects as load_projects,
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


class ProjectCreate(BaseModel):
    """Input accepted when creating a project."""

    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


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
    try:
        saved_memory = store_memory(
            content=memory.content,
            project=memory.project,
            memory_type=memory.memory_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "success": True,
        "data": saved_memory,
    }


@app.get("/memories")
def list_memories(project: Optional[str] = None) -> dict[str, Any]:
    """List saved memories, optionally filtered by project."""
    try:
        memories = load_memories(project=project)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"success": True, "data": memories}


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


@app.get("/projects")
def list_projects() -> dict[str, Any]:
    """List all available projects."""
    return {"success": True, "data": load_projects()}


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(project: ProjectCreate) -> dict[str, Any]:
    """Create a project."""
    try:
        saved_project = store_project(
            name=project.name,
            description=project.description,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "data": saved_project}
