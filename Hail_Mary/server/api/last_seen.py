"""POST /api/v1/last-seen/{zone_id}, GET /api/v1/last-seen,
GET /api/v1/last-seen/{zone_id}/image (대시보드 "마지막 목격 이미지" 카드).

Persists the single most-recent "zone went empty" frame per zone_id, uploaded
by the Camera side (M2/M3 edge). Only one image is kept per zone_id -- each
upload replaces the previous one (not an accumulating log), enforced by the
`last_seen_image.zone_id` PRIMARY KEY + INSERT OR REPLACE.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from Hail_Mary.server.api.deps import get_db, require_api_key

router = APIRouter(prefix="/api/v1/last-seen", tags=["last-seen"])

IMAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "last_seen"


class LastSeenUploadResponse(BaseModel):
    zone_id: str
    captured_at: str


class LastSeenEntry(BaseModel):
    zone_id: str
    captured_at: str
    image_url: str


def is_valid_zone_id(zone_id: str) -> bool:
    """Reject zone_ids that could escape IMAGE_DIR when used as a filename
    (path traversal via "..", "/", or "\\")."""
    if not zone_id:
        return False
    return not any(token in zone_id for token in ("..", "/", "\\"))


def image_path_for(zone_id: str, image_dir: "Path | None" = None) -> Path:
    # image_dir defaults to the *current* module-level IMAGE_DIR (looked up
    # at call time, not def time) so tests can monkeypatch IMAGE_DIR and have
    # the router functions (which call this with no image_dir) pick it up.
    if image_dir is None:
        image_dir = IMAGE_DIR
    return image_dir / f"{zone_id}.jpg"


def save_last_seen_image(
    conn: sqlite3.Connection,
    zone_id: str,
    image_bytes: bytes,
    captured_at: str,
    image_dir: "Path | None" = None,
) -> None:
    """Write the JPEG to disk and upsert the (zone_id -> captured_at, path)
    row, replacing whatever was previously stored for this zone_id."""
    if image_dir is None:
        image_dir = IMAGE_DIR
    image_dir.mkdir(parents=True, exist_ok=True)
    path = image_path_for(zone_id, image_dir)
    path.write_bytes(image_bytes)
    conn.execute(
        "INSERT OR REPLACE INTO last_seen_image (zone_id, captured_at, image_path) VALUES (?, ?, ?)",
        (zone_id, captured_at, str(path)),
    )
    conn.commit()


def list_last_seen(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT zone_id, captured_at FROM last_seen_image ORDER BY zone_id ASC"
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("/{zone_id}", response_model=LastSeenUploadResponse, dependencies=[Depends(require_api_key)])
async def upload_last_seen_image(zone_id: str, image: UploadFile, conn: sqlite3.Connection = Depends(get_db)):
    if not is_valid_zone_id(zone_id):
        raise HTTPException(status_code=400, detail="invalid zone_id")
    image_bytes = await image.read()
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # save_last_seen_image() does a blocking disk write + sqlite commit --
    # this route is `async def` (UploadFile.read() needs it), so without
    # offloading, that blocking call runs directly on the event loop thread
    # and stalls every other in-flight request for its duration.
    await run_in_threadpool(save_last_seen_image, conn, zone_id, image_bytes, captured_at)
    return LastSeenUploadResponse(zone_id=zone_id, captured_at=captured_at)


@router.get("", response_model=List[LastSeenEntry])
def get_all_last_seen(conn: sqlite3.Connection = Depends(get_db)):
    return [
        LastSeenEntry(
            zone_id=row["zone_id"],
            captured_at=row["captured_at"],
            image_url=f"/api/v1/last-seen/{row['zone_id']}/image",
        )
        for row in list_last_seen(conn)
    ]


@router.get("/{zone_id}/image")
def get_last_seen_image(zone_id: str):
    if not is_valid_zone_id(zone_id):
        raise HTTPException(status_code=400, detail="invalid zone_id")
    path = image_path_for(zone_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no image for zone_id")
    return Response(content=path.read_bytes(), media_type="image/jpeg")
