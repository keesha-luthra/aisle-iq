# PROMPT: Implement a cross-camera visitor re-identification (Re-ID) system so that visitors retain a stable global identity as they move across different camera fields of view.
# CHANGES MADE: Created pipeline/global_id.py containing GlobalIdentityService with cosine similarity thresholding, homography speed validation (<3.5m/s), temporal windowing (60s), and staff exclusion.

import uuid
import os
import json
from typing import Tuple, List, Optional, Dict
from datetime import datetime, timezone
import numpy as np
from pipeline.tracker import VisitorTracker

try:
    import cv2
except ImportError:
    cv2 = None

import structlog
logger = structlog.get_logger()

class GlobalIdentityService(VisitorTracker):
    """
    Manages global visitor identities across multiple camera streams.
    Inherits from VisitorTracker to maintain compatibility with existing pipeline,
    but implements keying by (camera_id, track_id) to avoid local tracker ID collisions.
    Integrates spatial-temporal speed constraints and staff exclusion.
    """
    def __init__(self, store_layout_path: str, reid_threshold: float = 0.75, 
                 reentry_window_seconds: int = 60, device: str | None = None):
        super().__init__(reid_threshold=reid_threshold, reentry_window_seconds=reentry_window_seconds, device=device)
        self.store_layout_path = store_layout_path
        self.visitor_last_foot_point: Dict[str, Tuple[Tuple[float, float], str]] = {} # visitor_id -> (foot_point, camera_id)
        self.latest_match_info: Dict[Tuple[str, int], dict] = {} # (camera_id, track_id) -> dict
        self.staff_classifier = None
        self.homography: Dict[str, np.ndarray] = {}

        # Load store layout and build homography transforms
        if store_layout_path and os.path.exists(store_layout_path):
            try:
                with open(store_layout_path, "r", encoding="utf-8") as f:
                    layout = json.load(f)
                cameras = layout.get("cameras", {})
                for cam_id, config in cameras.items():
                    src_pts = config.get("homography_src_points")
                    dst_pts = config.get("homography_dst_points")
                    if cv2 is not None and src_pts and dst_pts and len(src_pts) == 4 and len(dst_pts) == 4:
                        src_arr = np.array(src_pts, dtype=np.float32)
                        dst_arr = np.array(dst_pts, dtype=np.float32)
                        self.homography[cam_id] = cv2.getPerspectiveTransform(src_arr, dst_arr)
                logger.info("GlobalIdentityService loaded homographies", camera_count=len(self.homography))
            except Exception as e:
                logger.warn("Failed to load store layout homographies in GlobalIdentityService", error=str(e))

    def project_point(self, foot_point: Tuple[float, float], camera_id: str) -> Optional[Tuple[float, float]]:
        """
        Projects foot point coordinates to 2D store layout coordinates (in mm) using homography.
        """
        if cv2 is not None and camera_id in self.homography:
            pt_in = np.array([[[foot_point[0], foot_point[1]]]], dtype=np.float32)
            pt_out = cv2.perspectiveTransform(pt_in, self.homography[camera_id])
            return (float(pt_out[0][0][0]), float(pt_out[0][0][1]))
        return None

    def verify_speed_constraint(self, curr_foot: Tuple[float, float], curr_cam: str,
                                  prev_foot: Tuple[float, float], prev_cam: str,
                                  elapsed_seconds: float) -> bool:
        """
        Validates whether the transition speed between two cameras is physically possible (< 3.5 m/s).
        """
        if curr_cam == prev_cam:
            return True
            
        curr_proj = self.project_point(curr_foot, curr_cam)
        prev_proj = self.project_point(prev_foot, prev_cam)
        
        if curr_proj is not None and prev_proj is not None:
            dx = curr_proj[0] - prev_proj[0]
            dy = curr_proj[1] - prev_proj[1]
            dist_mm = np.sqrt(dx*dx + dy*dy)
            dist_meters = dist_mm / 1000.0
            
            if elapsed_seconds <= 0.1:
                # Disallow near-instantaneous transitions across different cameras
                return False
                
            speed = dist_meters / elapsed_seconds
            if speed > 3.5:
                logger.info("Impossible velocity detected between cameras, rejecting Re-ID match",
                            speed_mps=speed, dist_m=dist_meters, dt_sec=elapsed_seconds,
                            from_cam=prev_cam, to_cam=curr_cam)
                return False
        return True

    def get_visitor_id(self, track_id: int, frame: np.ndarray, bbox: tuple, 
                       camera_id: str = "CAM_GENERIC_01", frame_time: datetime | None = None) -> Tuple[str, bool]:
        """
        Resolves a local track ID to a global identity visitor ID.
        Uses (camera_id, track_id) keying to prevent local ID collision.
        """
        if frame_time is None:
            from datetime import timezone
            frame_time = datetime.now(timezone.utc)

        # Calculate foot point: bottom center
        x1, y1, x2, y2 = [float(c) for c in bbox]
        foot_point = (x1 + (x2 - x1) / 2.0, y2)

        key = (camera_id, track_id)
        
        # If track is already mapped on this camera, return cached mapping
        if key in self.track_to_visitor:
            visitor_id = self.track_to_visitor[key]
            self.visitor_last_seen[visitor_id] = frame_time
            self.visitor_last_foot_point[visitor_id] = (foot_point, camera_id)
            return (visitor_id, False)

        # Extract appearance embedding
        embedding = self.embedding_extractor.extract(frame, bbox)
        
        # Search registered gallery for matches
        best_match_id = None
        best_similarity = 0.0
        prev_camera_id = None
        
        for vid, emb in self.visitor_embeddings.items():
            # Exclude staff members
            if self.staff_classifier and self.staff_classifier.cache.get(vid, False):
                continue
                
            # Check temporal window constraint
            if vid in self.visitor_last_seen:
                last_seen = self.visitor_last_seen[vid]
                elapsed = abs((frame_time - last_seen).total_seconds())
                if elapsed <= self.reentry_window_seconds:
                    # cosine similarity (both normalized)
                    sim = float(np.dot(embedding, emb))
                    if sim > best_similarity:
                        # Verify spatial-speed constraints
                        spatial_ok = True
                        if vid in self.visitor_last_foot_point:
                            prev_foot, prev_cam = self.visitor_last_foot_point[vid]
                            spatial_ok = self.verify_speed_constraint(
                                foot_point, camera_id, prev_foot, prev_cam, elapsed
                            )
                            
                        if spatial_ok:
                            best_similarity = sim
                            best_match_id = vid
                            if vid in self.visitor_last_foot_point:
                                prev_camera_id = self.visitor_last_foot_point[vid][1]

        if best_match_id and best_similarity >= self.reid_threshold:
            # Match succeeded
            visitor_id = best_match_id
            self.track_to_visitor[key] = visitor_id
            self.visitor_exit_times.pop(visitor_id, None)
            
            # Record match details
            self.latest_match_info[key] = {
                "local_tracker_id": str(track_id),
                "reid_confidence": float(best_similarity),
                "source_camera": prev_camera_id,
                "destination_camera": camera_id
            }
            
            # Update rolling mean embedding
            new_emb = 0.9 * self.visitor_embeddings[visitor_id] + 0.1 * embedding
            norm = np.linalg.norm(new_emb)
            self.visitor_embeddings[visitor_id] = new_emb / norm if norm > 0 else new_emb
            
            self.visitor_last_seen[visitor_id] = frame_time
            self.visitor_last_foot_point[visitor_id] = (foot_point, camera_id)
            return (visitor_id, True)

        # Create new global visitor ID
        visitor_id = "VIS_" + uuid.uuid4().hex[:6]
        self.track_to_visitor[key] = visitor_id
        self.visitor_embeddings[visitor_id] = embedding
        self.visitor_last_seen[visitor_id] = frame_time
        self.visitor_last_foot_point[visitor_id] = (foot_point, camera_id)
        return (visitor_id, False)

    def mark_exited(self, visitor_id: str, exit_time: datetime):
        """
        Marks global visitor exited and removes active tracker associations.
        """
        self.visitor_exit_times[visitor_id] = exit_time
        stale_keys = [k for k, v in self.track_to_visitor.items() if v == visitor_id]
        for k in stale_keys:
            del self.track_to_visitor[k]

    def get_latest_match(self, camera_id: str, track_id: int) -> Optional[dict]:
        """
        Returns latest cross-camera match metadata for a local track ID.
        """
        return self.latest_match_info.get((camera_id, track_id))
