"""FastAPI sidecar exposing bge-m3 embeddings over HTTP.

Usage
-----
    python -m pantryatlas.embeddings_server
    # or
    uvicorn pantryatlas.embeddings_server:app --host 0.0.0.0 --port 8000

Endpoints
---------
    POST /embed
        Request : {"texts": ["string", ...]}
        Response: {"vectors": [[float, ...], ...]}  — shape (N, 1024)
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from pantryatlas.embeddings import embed

app = FastAPI(
    title="pantryatlas embedding sidecar",
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
