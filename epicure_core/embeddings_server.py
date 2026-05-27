"""FastAPI sidecar exposing bge-m3 embeddings over HTTP.

Usage
-----
    python -m epicure_core.embeddings_server
    # or
    uvicorn epicure_core.embeddings_server:app --host 0.0.0.0 --port 8000

Endpoints
---------
    POST /embed
        Request : {"texts": ["string", ...]}
        Response: {"vectors": [[float, ...], ...]}  — shape (N, 1024)
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from epicure_core.embeddings import embed

app = FastAPI(
    title="epicure-core embedding sidecar",
    description="bge-m3 int8 ONNX embedding service",
    version="0.1.0",
)


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    vectors: list[list[float]]


@app.post("/embed", response_model=EmbedResponse)
def embed_endpoint(req: EmbedRequest) -> EmbedResponse:
    """Embed a list of strings and return unit-norm float32 vectors."""
    return EmbedResponse(vectors=embed(req.texts).tolist())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
