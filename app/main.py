"""URL shortener API.

A deliberately small service whose real purpose is to exercise a production-style
delivery pipeline: health/readiness probes for Kubernetes, Prometheus metrics,
structured config via environment variables, and a test suite CI can gate on.
"""

import os
import secrets
import string
import time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, HttpUrl

from app.store import MemoryStore

ALPHABET = string.ascii_letters + string.digits
CODE_LENGTH = int(os.getenv("CODE_LENGTH", "7"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
VERSION = os.getenv("APP_VERSION", "dev")

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["method", "route"])
REDIRECTS = Counter("shortener_redirects_total", "Successful short link redirects")

app = FastAPI(title="url-shortener", version=VERSION)
store = MemoryStore()


class ShortenRequest(BaseModel):
    url: HttpUrl
    code: str | None = None


class ShortenResponse(BaseModel):
    code: str
    short_url: str
    url: str


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    # Use the route template, not the raw path, to keep label cardinality bounded
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


def new_code() -> str:
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        if not store.exists(code):
            return code
    raise HTTPException(status_code=503, detail="could not allocate a short code")


@app.post("/api/v1/links", response_model=ShortenResponse, status_code=201)
def shorten(req: ShortenRequest) -> ShortenResponse:
    code = req.code or new_code()
    if req.code:
        if not (3 <= len(code) <= 32) or any(c not in ALPHABET + "-_" for c in code):
            raise HTTPException(status_code=422, detail="code must be 3-32 chars of [A-Za-z0-9-_]")
        if store.exists(code):
            raise HTTPException(status_code=409, detail="code already in use")
    store.put(code, str(req.url))
    return ShortenResponse(code=code, short_url=f"{BASE_URL}/{code}", url=str(req.url))


@app.get("/api/v1/links/{code}", response_model=ShortenResponse)
def get_link(code: str) -> ShortenResponse:
    url = store.get(code)
    if url is None:
        raise HTTPException(status_code=404, detail="not found")
    return ShortenResponse(code=code, short_url=f"{BASE_URL}/{code}", url=url)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok", "version": VERSION}


@app.get("/readyz", include_in_schema=False)
def readyz() -> dict:
    if not store.ping():
        raise HTTPException(status_code=503, detail="store unavailable")
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/{code}", include_in_schema=False)
def follow(code: str) -> RedirectResponse:
    url = store.get(code)
    if url is None:
        raise HTTPException(status_code=404, detail="not found")
    REDIRECTS.inc()
    return RedirectResponse(url, status_code=307)
