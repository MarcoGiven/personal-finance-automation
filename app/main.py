
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.plaid_link import router as plaid_router
from app.review import router as review_router
from app.conflicts import router as conflicts_router
from app.workflow import router as workflow_router

app = FastAPI(title="Personal Finance Automation")

app.include_router(plaid_router)
app.include_router(review_router)
app.include_router(conflicts_router)
app.include_router(workflow_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def home():
    return {
        "message": "Personal Finance API is running"
    }


@app.get("/connect")
def connect_page():
    return FileResponse(STATIC_DIR / "connect.html")


@app.get("/review")
def review_page():
    return FileResponse(STATIC_DIR / "review.html")
