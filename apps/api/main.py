"""GigBid FastAPI application (routers are added per phase)."""

from fastapi import FastAPI

app = FastAPI(title="GigBid API", version="1.0.0")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gigbid-api"}
