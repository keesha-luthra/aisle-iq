"""
Video streaming router.

Serves raw MP4 files from data/clips/ with HTTP range-request support so that
Streamlit's st.video() can play them directly from the API.

Endpoint:
    GET /video/{store_id}/{camera_id}

Camera-to-file mapping (STORE_BLR_002):
    CAM_01  →  data/clips/CAM 1 - zone.mp4
    CAM_02  →  data/clips/CAM 2 - zone.mp4
    CAM_03  →  data/clips/CAM 3 - entry.mp4
    CAM_05  →  data/clips/CAM 5 - billing.mp4

Camera-to-file mapping (STORE_MUM_076):
    CAM_01  →  data/clips_store2/entry 1.mp4
    CAM_02  →  data/clips_store2/entry 2.mp4
    CAM_03  →  data/clips_store2/zone.mp4
    CAM_05  →  data/clips_store2/billing_area.mp4
"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, Response

router = APIRouter()

# Base directory of the project (two levels up from this file: app/routers/video.py)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Camera-to-file mapping per store (original clips)
_STORE_CAMERA_MAP: dict[str, dict[str, str]] = {
    "STORE_BLR_002": {
        "CAM_01": str(_BASE_DIR / "data" / "clips" / "CAM 1 - zone.mp4"),
        "CAM_02": str(_BASE_DIR / "data" / "clips" / "CAM 2 - zone.mp4"),
        "CAM_03": str(_BASE_DIR / "data" / "clips" / "CAM 3 - entry.mp4"),
        "CAM_05": str(_BASE_DIR / "data" / "clips" / "CAM 5 - billing.mp4"),
    },
    "STORE_MUM_076": {
        "CAM_01": str(_BASE_DIR / "data" / "clips_store2" / "entry 1.mp4"),
        "CAM_02": str(_BASE_DIR / "data" / "clips_store2" / "entry 2.mp4"),
        "CAM_03": str(_BASE_DIR / "data" / "clips_store2" / "zone.mp4"),
        "CAM_05": str(_BASE_DIR / "data" / "clips_store2" / "billing_area.mp4"),
    },
}

_CHUNK_SIZE = 1024 * 1024  # 1 MB per chunk


def _get_video_path(store_id: str, camera_id: str) -> str:
    """
    Resolve the file path for a given store+camera combination.
    Prefers annotated output (data/annotated/{store_id}/{camera_id}.mp4)
    over the original clip when an annotated version has been generated.
    """
    # 1. Check for annotated output first
    annotated_path = str(_BASE_DIR / "data" / "annotated" / store_id / f"{camera_id}.mp4")
    if os.path.isfile(annotated_path):
        return annotated_path

    # 2. Fall back to original clip
    store_map = _STORE_CAMERA_MAP.get(store_id)
    if store_map is None:
        raise HTTPException(status_code=404, detail=f"Unknown store_id: {store_id}")
    video_path = store_map.get(camera_id)
    if video_path is None:
        raise HTTPException(status_code=404, detail=f"No video mapped for camera {camera_id} in store {store_id}")
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=404, detail=f"Video file not found on disk: {video_path}")
    return video_path


@router.get("/{store_id}/{camera_id}", summary="Stream camera video feed")
async def stream_camera_video(store_id: str, camera_id: str, request: Request):
    """
    Streams the mp4 video for the given store/camera with HTTP Range support.
    Streamlit st.video() uses this endpoint to play videos directly.
    """
    video_path = _get_video_path(store_id, camera_id)
    file_size = os.path.getsize(video_path)

    range_header = request.headers.get("range")

    if range_header:
        # Parse: "bytes=start-end"
        try:
            range_val = range_header.strip().replace("bytes=", "")
            start_str, _, end_str = range_val.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid Range header")

        end = min(end, file_size - 1)
        chunk_length = end - start + 1

        def iter_file_range():
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = chunk_length
                while remaining > 0:
                    data = f.read(min(_CHUNK_SIZE, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_length),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iter_file_range(), status_code=206, headers=headers, media_type="video/mp4")

    # Full file response (no range requested)
    def iter_full_file():
        with open(video_path, "rb") as f:
            while True:
                data = f.read(_CHUNK_SIZE)
                if not data:
                    break
                yield data

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": "video/mp4",
    }
    return StreamingResponse(iter_full_file(), status_code=200, headers=headers, media_type="video/mp4")


@router.get("/{store_id}/{camera_id}/info", summary="Get video metadata")
async def get_video_info(store_id: str, camera_id: str):
    """Returns metadata for the video file (size, path existence, whether annotated)."""
    # Check annotated first
    annotated_path = str(_BASE_DIR / "data" / "annotated" / store_id / f"{camera_id}.mp4")
    is_annotated = os.path.isfile(annotated_path)

    video_path = _get_video_path(store_id, camera_id)
    file_size = os.path.getsize(video_path)
    return {
        "store_id": store_id,
        "camera_id": camera_id,
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 1),
        "available": True,
        "annotated": is_annotated,
        "stream_url": f"/video/{store_id}/{camera_id}",
    }
