"""Local-only buttons for the existing Plaid and Google Sheets CLIs."""
import asyncio
import ipaddress
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/workflow", tags=["Workflow"])
ROOT = Path(__file__).resolve().parent.parent
_busy = threading.Lock()
MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


class SyncRequest(BaseModel):
    month: str


def require_local(request: Request):
    """Reject remote clients and cross-origin browser submissions."""
    host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise HTTPException(403, "This action is available only on localhost")
    except ValueError:
        raise HTTPException(403, "This action is available only on localhost")

    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:8000", "http://localhost:8000"}:
        raise HTTPException(403, "Cross-origin requests are not permitted")


def run_command(args: list[str], timeout: int):
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "Another fetch or sync is already running")
    try:
        try:
            result = subprocess.run(
                [sys.executable, "-m", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Command timed out. Check the database and spreadsheet before retrying")
        output = "\n".join(filter(None, (result.stdout.strip(), result.stderr.strip())))
        if result.returncode != 0:
            raise HTTPException(500, output[-6000:] or "Command failed")
        return {"success": True, "output": output[-12000:]}
    finally:
        _busy.release()


@router.post("/fetch")
async def fetch_transactions(request: Request):
    require_local(request)
    return await asyncio.to_thread(run_command, ["app.plaid_sync", "--write"], 240)


@router.post("/sync")
async def sync_approved(request: Request, payload: SyncRequest):
    require_local(request)
    if payload.month not in MONTHS:
        raise HTTPException(400, "Select a valid budget month")
    return await asyncio.to_thread(
        run_command, ["app.sync", "--month", payload.month, "--write"], 300
    )
