from fastapi import FastAPI

app = FastAPI(
    title="MootOS",
    description="The backend foundation for MootOS.",
    version="0.1.0",
)


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

    return {
        "status": "healthy",
    }
