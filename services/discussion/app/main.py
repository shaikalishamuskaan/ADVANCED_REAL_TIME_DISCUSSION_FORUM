from fastapi import FastAPI

app = FastAPI(
    title="Discussion Service",
    description="Core discussion management service",
    version="1.0.0",
)


@app.get("/health")
async def health_check():
    return {
        "service": "discussion",
        "status": "healthy",
    }