
import ipaddress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.plaid_link import router as plaid_router
from app.review import router as review_router
from app.conflicts import router as conflicts_router
from app.workflow import router as workflow_router


app = FastAPI(title="Personal Finance Automation")

# Only accept requests addressed to localhost.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["127.0.0.1", "localhost"],
)


@app.middleware("http")
async def restrict_local_access(request: Request, call_next):
    # Restrict connections to the local computer.
    client_host = request.client.host if request.client else ""

    try:
        allowed = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        allowed = False

    if not allowed:
        return JSONResponse(
            status_code=403,
            content={"detail": "Local access only"},
        )

    # Require the expected browser origin for state-changing requests.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")

        expected = {
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        }

        if origin not in expected:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid request origin"},
            )

    return await call_next(request)


# API routers
app.include_router(plaid_router)
app.include_router(review_router)
app.include_router(conflicts_router)
app.include_router(workflow_router)


STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def home():
    return {"message": "Personal Finance API is running"}


@app.get("/connect")
def connect_page():
    return FileResponse(STATIC_DIR / "connect.html")


@app.get("/review")
def review_page():
    return FileResponse(STATIC_DIR / "review.html")
