import argparse
import os
import sys
import json
import cv2
import torch
from datetime import datetime, timezone, timedelta
from typing import List
from ultralytics import YOLO
from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn, TaskProgressColumn
import structlog

# Initialize structured logging
logger = structlog.get_logger()

# Import pipeline components
from pipeline.tracker import VisitorTracker
from pipeline.staff import StaffClassifier
from pipeline.zones import ZoneMapper
from pipeline.state_machine import PipelineStateMachine

# ─── Annotation colour palette ────────────────────────────────────────────────
_ANN_CYAN  = (254, 242, 0)   # BGR: visitor bbox (cyan in RGB → yellow-ish in BGR display = 0xFEF200 is wrong; use real cyan)
_ANN_CYAN  = (254, 242, 0)   # BGR cyan  00F2FE  → (254, 242, 0) wrong; correct BGR:
_ANN_CYAN  = (0xFE, 0xF2, 0x00)  # 0x00F2FE in RGB → BGR = (0xFE, 0xF2, 0x00)
_ANN_CYAN  = (254, 242, 0)        # visitor: neon cyan   #00F2FE  -> BGR (254,242,0)
# Let's define properly:
_COLOR_VISITOR = (254, 242,   0)   # #00F2FE  in BGR  (neon cyan)
_COLOR_STAFF   = ( 88,  85, 243)   # #F35558  in BGR  (neon pink)
_COLOR_REENTRY = (  0, 230,  77)   # #4DE600  in BGR  (neon green)
_COLOR_OVERLAY = (255, 255, 255)   # white text
_FONT          = cv2.FONT_HERSHEY_SIMPLEX


class VideoProcessor:
    """
    Main orchestrator that runs YOLOv8 detection, Re-ID tracking, staff classification,
    zone mapping, and state machine event logic on video clips.
    """
    def __init__(self, store_layout_path: str, store_id: str | None = None, 
                 fps_process: int = 5, device: str | None = None):
        
        # Load store_layout.json
        if not os.path.exists(store_layout_path):
            raise FileNotFoundError(f"Store layout file not found at: {store_layout_path}")
            
        with open(store_layout_path, "r", encoding="utf-8") as f:
            self.store_layout = json.load(f)
            
        self.store_id = store_id or self.store_layout.get("store_id", "STORE_GENERIC_01")
        self.fps_process = max(1, min(15, fps_process))
        
        # Select device
        if not device:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        logger.info("Initializing VideoProcessor", store_id=self.store_id, 
                    fps_process=self.fps_process, device=self.device)
        
        # Initialize YOLOv8 model
        self.model = YOLO("yolov8n.pt")
        # Initialize modules
        from app.config import settings
        from pipeline.global_id import GlobalIdentityService
        self.tracker = GlobalIdentityService(
            store_layout_path=store_layout_path,
            reid_threshold=settings.REID_THRESHOLD,
            reentry_window_seconds=1800,
            device=self.device
        )
        self.staff_classifier = StaffClassifier(
            confidence_threshold=0.70, 
            min_track_age_seconds=5.0, 
            device=self.device
        )
        self.tracker.staff_classifier = self.staff_classifier
        self.zone_mapper = ZoneMapper(store_layout_path)
        self.state_machine = PipelineStateMachine(
            zone_mapper=self.zone_mapper,
            staff_classifier=self.staff_classifier,
            tracker=self.tracker,
            inactivity_timeout_seconds=30.0
        )
        self.track_ages = {}



    def _parse_clip_start_time(self, clip_path: str) -> datetime:
        """
        Parses starting timestamp from filename if format is YYYYMMDD_HHMMSS.mp4,
        else uses file modification time (mtime), converted to UTC ISO-8601.
        """
        filename = os.path.basename(clip_path)
        name_without_ext, _ = os.path.splitext(filename)
        
        try:
            # Look for YYYYMMDD_HHMMSS pattern (15 chars)
            # format: YYYYMMDD_HHMMSS.mp4
            parts = name_without_ext.split("_")
            for part in parts:
                if len(part) == 15 and part[8] == "T":
                    # YYYYMMDDTHHMMSS
                    return datetime.strptime(part, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                elif len(part) == 8 and len(parts) >= 2:
                    # check YYYYMMDD_HHMMSS
                    # find if there is another part representing HHMMSS
                    idx = parts.index(part)
                    if idx + 1 < len(parts) and len(parts[idx+1]) == 6:
                        dt_str = f"{part}_{parts[idx+1]}"
                        return datetime.strptime(dt_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass

        # Fallback to file mtime converted to UTC
        mtime = os.path.getmtime(clip_path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc)

    # ── Annotation helpers ──────────────────────────────────────────────────────

    def _process_frame(self, frame, frame_timestamp, camera_id) -> tuple[list, list]:
        """
        Runs inference on a single frame, processes tracking, and feeds the state machine.
        Returns a tuple of (emitted_events, frame_detections).
        """
        emitted_events = []
        frame_detections = []

        # 1. YOLO inference
        results = self.model.track(frame, persist=True, verbose=False, classes=[0], tracker="botsort.yaml")
        boxes = results[0].boxes

        if boxes is None or boxes.id is None:
            self.state_machine.handle_empty_period(frame_timestamp, self.store_id)
            evicted_events = self.state_machine.flush_pending()
            emitted_events.extend(evicted_events)
            for event in evicted_events:
                if event["event_type"] == "EXIT":
                    self.staff_classifier.clear_visitor(event["visitor_id"])
                    self.tracker.mark_exited(event["visitor_id"], frame_timestamp)
            return emitted_events, frame_detections

        # Process detection boxes for this frame
        for box in boxes:
            if box.id is None:
                continue

            track_id = int(box.id[0].item())
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bbox = (x1, y1, x2, y2)
            confidence = float(box.conf[0].item())

            # Track age logic
            self.track_ages[track_id] = self.track_ages.get(track_id, 0) + 1
            track_age = self.track_ages[track_id]

            # Calibrate confidence
            calibrated_confidence = self.handle_partial_occlusion(confidence, track_age)

            # Foot point: bottom-center coordinates of the bounding box
            foot_point = (x1 + (x2 - x1) / 2.0, y2)

            # Get zone ID
            zone_id = self.zone_mapper.get_zone(foot_point, camera_id)

            # Assign global ReID visitor_id
            visitor_id, is_reentry = self.tracker.get_visitor_id(
                track_id, frame, bbox, camera_id, frame_timestamp
            )

            reid_meta = {}
            if is_reentry and hasattr(self.tracker, "get_latest_match"):
                match_info = self.tracker.get_latest_match(camera_id, track_id)
                if match_info:
                    reid_meta = {
                        "local_tracker_id": match_info.get("local_tracker_id"),
                        "reid_confidence": match_info.get("reid_confidence"),
                        "source_camera": match_info.get("source_camera"),
                        "destination_camera": match_info.get("destination_camera"),
                    }

            # Classify staff vs visitor
            self.staff_classifier.update_crop(
                visitor_id, frame, bbox, frame_timestamp, calibrated_confidence
            )
            is_staff, _ = self.staff_classifier.classify(
                visitor_id, frame_timestamp
            )

            frame_detections.append(
                {
                    "bbox": bbox,
                    "visitor_id": visitor_id,
                    "confidence": calibrated_confidence,
                    "original_confidence": confidence,
                    "is_staff": is_staff,
                    "zone_id": zone_id,
                    "is_reentry": is_reentry,
                    "track_age": track_age,
                    "timestamp": frame_timestamp,
                    "reid_meta": reid_meta,
                }
            )

        # Handle group entries if there is any entry zone ID
        entry_zones = [
            d["zone_id"]
            for d in frame_detections
            if d["zone_id"] and self.zone_mapper.is_entry_zone(d["zone_id"])
        ]
        if entry_zones:
            self.handle_group_entry(frame_detections, entry_zones[0])

        # Estimate queue depth
        billing_dets = [
            d
            for d in frame_detections
            if d["zone_id"] and self.zone_mapper.is_billing_zone(d["zone_id"])
        ]
        queue_depth = self.estimate_queue_depth(billing_dets)

        # Feed each detection to the state machine
        for d in frame_detections:
            meta = {}
            if d["original_confidence"] < 0.5 and d["track_age"] < 10:
                meta["possibly_occluded"] = True

            if d.get("reid_meta"):
                meta.update(d["reid_meta"])

            events = self.state_machine.update(
                visitor_id=d["visitor_id"],
                zone_id=d["zone_id"],
                is_staff=d["is_staff"],
                confidence=d["confidence"],
                store_id=self.store_id,
                camera_id=camera_id,
                timestamp=frame_timestamp,
                is_reentry=d["is_reentry"],
                metadata=meta,
            )
            emitted_events.extend(events)

            # Handle queue join if in billing zone and not staff
            if (
                d["zone_id"]
                and self.zone_mapper.is_billing_zone(d["zone_id"])
                and not d["is_staff"]
            ):
                queue_events = self.state_machine.handle_billing_queue_join(
                    visitor_id=d["visitor_id"],
                    queue_depth=queue_depth,
                    camera_id=camera_id,
                    frame_time=frame_timestamp,
                    store_id=self.store_id,
                )
                emitted_events.extend(queue_events)

            for event in events:
                if event["event_type"] == "EXIT":
                    self.staff_classifier.clear_visitor(event["visitor_id"])
                    self.tracker.mark_exited(event["visitor_id"], frame_timestamp)

        # 4. Evict stale visitors who were not detected in this frame
        self.state_machine.handle_empty_period(frame_timestamp, self.store_id)
        evicted_events = self.state_machine.flush_pending()
        emitted_events.extend(evicted_events)
        for event in evicted_events:
            if event["event_type"] == "EXIT":
                self.staff_classifier.clear_visitor(event["visitor_id"])
                self.tracker.mark_exited(event["visitor_id"], frame_timestamp)

        return emitted_events, frame_detections
    @staticmethod
    def _draw_corner_box(img, x1: int, y1: int, x2: int, y2: int, color, thickness: int = 2, corner_len: int = 14):
        """Draws a bounding box with corner-bracket markers (CCTV-style)."""
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
        # Top-left
        cv2.line(img, (x1, y1), (x1 + corner_len, y1), color, thickness)
        cv2.line(img, (x1, y1), (x1, y1 + corner_len), color, thickness)
        # Top-right
        cv2.line(img, (x2, y1), (x2 - corner_len, y1), color, thickness)
        cv2.line(img, (x2, y1), (x2, y1 + corner_len), color, thickness)
        # Bottom-left
        cv2.line(img, (x1, y2), (x1 + corner_len, y2), color, thickness)
        cv2.line(img, (x1, y2), (x1, y2 - corner_len), color, thickness)
        # Bottom-right
        cv2.line(img, (x2, y2), (x2 - corner_len, y2), color, thickness)
        cv2.line(img, (x2, y2), (x2, y2 - corner_len), color, thickness)

    @staticmethod
    def _put_label(img, text: str, x: int, y: int, color, bg_color=(0, 0, 0), font_scale: float = 0.42, thickness: int = 1):
        """Draws text with a filled background rectangle for readability."""
        (tw, th), baseline = cv2.getTextSize(text, _FONT, font_scale, thickness)
        pad = 3
        cv2.rectangle(img, (x - pad, y - th - pad), (x + tw + pad, y + baseline + pad), bg_color, -1)
        cv2.putText(img, text, (x, y), _FONT, font_scale, color, thickness, cv2.LINE_AA)

    def _draw_frame_annotations(
        self,
        frame,
        detections: list,
        camera_id: str,
        frame_timestamp,
        frame_w: int,
        frame_h: int,
    ):
        """
        Draws all bounding boxes, global visitor IDs, confidence, zone labels,
        and the camera overlay (name, LIVE badge, timestamp) on a copy of `frame`.
        Returns the annotated frame.
        """
        out = frame.copy()

        # ── Per-detection bounding boxes ─────────────────────────────────────
        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
            vid      = det["visitor_id"]
            conf     = det["confidence"]
            is_staff = det["is_staff"]
            zone     = det.get("zone_id") or ""
            is_re    = det.get("is_reentry", False)

            color = _COLOR_STAFF if is_staff else (_COLOR_REENTRY if is_re else _COLOR_VISITOR)

            # Corner-bracket bounding box
            self._draw_corner_box(out, x1, y1, x2, y2, color, thickness=2)

            # Main label: global visitor ID
            role_tag = "[STAFF]" if is_staff else ("[RE-ID]" if is_re else "")
            main_label = f"{vid} {role_tag}" if role_tag else vid
            self._put_label(out, main_label, x1, max(y1 - 4, 14), color, bg_color=(20, 20, 20))

            # Secondary label: confidence + zone
            detail_parts = [f"Conf:{conf:.0%}"]
            if zone:
                detail_parts.append(zone)
            detail_label = "  ".join(detail_parts)
            self._put_label(out, detail_label, x1, min(y2 + 14, frame_h - 4),
                            _COLOR_OVERLAY, bg_color=(20, 20, 20), font_scale=0.35)

        # ── Camera overlay (top-right) ────────────────────────────────────────
        ts_str = frame_timestamp.strftime("%H:%M:%S") if frame_timestamp else ""
        cam_label = f"{camera_id}  |  {ts_str}"
        self._put_label(out, cam_label, frame_w - 175, 18,
                        _COLOR_OVERLAY, bg_color=(40, 40, 40), font_scale=0.4, thickness=1)

        # LIVE blinking indicator (always green dot)
        cv2.circle(out, (10, 10), 5, (0, 220, 60), -1)
        self._put_label(out, "LIVE", 20, 14, (0, 220, 60), bg_color=(20, 20, 20),
                        font_scale=0.38, thickness=1)

        # Active count badge (bottom-left)
        visitors_shown = [d for d in detections if not d["is_staff"]]
        badge = f"Visitors: {len(visitors_shown)}   Staff: {sum(1 for d in detections if d['is_staff'])}"
        self._put_label(out, badge, 6, frame_h - 8,
                        _COLOR_OVERLAY, bg_color=(30, 30, 30), font_scale=0.38)

        return out

    def process_clip(
        self,
        clip_path: str,
        camera_id: str,
        annotated_output_path: str | None = None,
    ) -> List[dict]:
        """
        Processes a single video clip and returns all emitted visitor events.

        Args:
            clip_path:             Path to the source MP4 clip.
            camera_id:             Camera identifier (e.g. ``'CAM_01'``).
            annotated_output_path: Optional path for the annotated output video.
                                   When provided, every frame is written with
                                   bounding-box overlays and global visitor IDs.
        """
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            logger.error("Failed to open video file", path=clip_path)
            return []

        try:
            clip_fps = cap.get(cv2.CAP_PROP_FPS)
            if clip_fps <= 0:
                clip_fps = 25.0  # fallback

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            clip_start_time = self._parse_clip_start_time(clip_path)

            frame_skip = max(1, round(clip_fps / self.fps_process))

            logger.info(
                "Processing clip details",
                camera_id=camera_id,
                fps=clip_fps,
                frames=total_frames,
                start_time=clip_start_time,
                frame_skip=frame_skip,
                annotate=bool(annotated_output_path),
            )

            # ── Optional annotated-video writer ──────────────────────────────
            writer = None
            if annotated_output_path:
                import pathlib
                pathlib.Path(annotated_output_path).parent.mkdir(parents=True, exist_ok=True)
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(
                    annotated_output_path, fourcc, clip_fps, (frame_w, frame_h)
                )
                if not writer.isOpened():
                    logger.warning("Could not open VideoWriter — skipping annotation",
                                   path=annotated_output_path)
                    writer = None

            # Tracks the latest detection list so we can carry annotations over
            # to skipped (non-processed) frames for a smooth output video.
            latest_detections: list = []
            latest_frame_ts = clip_start_time

            emitted_events = []
            frame_idx = 0

            # Rich progress layout
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TimeElapsedColumn(),
            ) as progress:
                task = progress.add_task(f"Camera {camera_id}", total=total_frames)
                
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        break

                    # Process frame at frame_skip intervals
                    if frame_idx % frame_skip == 0:
                        frame_timestamp = clip_start_time + timedelta(seconds=frame_idx / clip_fps)
                        latest_frame_ts = frame_timestamp
                        
                        events, latest_detections = self._process_frame(frame, frame_timestamp, camera_id)
                        emitted_events.extend(events)

                    # ── Write annotated frame to output video ────────────────
                    if writer is not None:
                        annotated_frame = self._draw_frame_annotations(
                            frame,
                            latest_detections,
                            camera_id,
                            latest_frame_ts,
                            frame_w,
                            frame_h,
                        )
                        writer.write(annotated_frame)

                    frame_idx += 1
                    progress.update(task, completed=frame_idx)
                    
            # End of clip: flush any remaining active sessions
            final_time = clip_start_time + timedelta(seconds=total_frames / clip_fps)
            flush_events = self.state_machine.clear_all(final_time)
            emitted_events.extend(flush_events)
            for event in flush_events:
                if event["event_type"] == "EXIT":
                    self.staff_classifier.clear_visitor(event["visitor_id"])
                    self.tracker.mark_exited(event["visitor_id"], final_time)

            if writer is not None:
                writer.release()
                logger.info(
                    "Annotated video saved",
                    path=annotated_output_path,
                    camera_id=camera_id,
                )

            return emitted_events

        finally:
            cap.release()

    def process_all_clips(self, clips_dir: str, output_dir: str):
        """
        Scans clips_dir, infers cameras, processes, and writes JSONL outputs.
        """
        if not os.path.exists(clips_dir):
            logger.error("Source clips directory does not exist", directory=clips_dir)
            return

        os.makedirs(output_dir, exist_ok=True)
        files = [f for f in os.listdir(clips_dir) if f.endswith((".mp4", ".avi", ".mkv"))]
        
        logger.info(f"Found {len(files)} clips to process in {clips_dir}")
        
        total_events = 0
        start_process_time = datetime.now()
        
        for file in files:
            clip_path = os.path.join(clips_dir, file)
            
            # Infer camera ID from name
            name_lower = file.lower()
            if "cam 1" in name_lower or "cam_01" in name_lower or "cam1" in name_lower:
                camera_id = "CAM_01"
            elif "cam 2" in name_lower or "cam_02" in name_lower or "cam2" in name_lower:
                camera_id = "CAM_02"
            elif "cam 3" in name_lower or "cam_03" in name_lower or "cam3" in name_lower:
                camera_id = "CAM_03"
            elif "cam 4" in name_lower or "cam_04" in name_lower or "cam4" in name_lower:
                camera_id = "CAM_04"
            elif "cam 5" in name_lower or "cam_05" in name_lower or "cam5" in name_lower:
                camera_id = "CAM_05"
            elif "entry" in name_lower:
                camera_id = "CAM_ENTRY_01"
            elif "floor" in name_lower:
                camera_id = "CAM_FLOOR_01"
            elif "billing" in name_lower:
                camera_id = "CAM_BILLING_01"
            else:
                camera_id = "CAM_GENERIC_01"

            logger.info("Starting clip processing", file=file, camera_id=camera_id)
            events = self.process_clip(clip_path, camera_id)
            total_events += len(events)
            
            # Save events to JSONL
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(output_dir, f"{camera_id}_{timestamp_str}.jsonl")
            
            with open(output_file, "w", encoding="utf-8") as out:
                for event in events:
                    out.write(json.dumps(event) + "\n")
                    
            logger.info("Events saved to file", output=output_file, count=len(events))
            
        elapsed = datetime.now() - start_process_time
        print("\n=== Processing Summary ===")
        print(f"Total Clips Processed : {len(files)}")
        print(f"Total Events Generated: {total_events}")
        print(f"Elapsed Time          : {elapsed.total_seconds():.2f} seconds")

    def estimate_queue_depth(self, billing_detections: List[dict]) -> int:
        """
        Estimates the queue depth in the billing zone.
        For now: just return len([d for d in billing_detections if not d['is_staff']]).
        """
        return len([d for d in billing_detections if not d.get('is_staff', False)])

    def handle_group_entry(self, frame_detections: List[dict], entry_zone_id: str) -> List[str]:
        """
        Handles grouping of people entering simultaneously through the same door.
        Filters detections by entry_zone_id, groups them by temporal proximity (0.5s window),
        logs group entry details, and returns the visitor IDs.
        """
        zone_dets = [d for d in frame_detections if d.get('zone_id') == entry_zone_id]
        if not zone_dets:
            return []
            
        if not hasattr(self, '_entry_history'):
            self._entry_history = []
            
        new_vids = set()
        for d in zone_dets:
            vid = d.get('visitor_id')
            if not vid:
                continue
            ts = d.get('timestamp')
            if not ts:
                ts = datetime.now(timezone.utc)
            elif isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.now(timezone.utc)
                    
            exists = any(h['visitor_id'] == vid for h in self._entry_history)
            if not exists:
                self._entry_history.append({'visitor_id': vid, 'timestamp': ts})
                new_vids.add(vid)
                
        if not self._entry_history:
            return []
            
        # Prune entry history older than 5.0 seconds from the latest timestamp
        latest_ts = max(h['timestamp'] for h in self._entry_history)
        self._entry_history = [h for h in self._entry_history if (latest_ts - h['timestamp']).total_seconds() <= 5.0]
        
        # Cluster history into 0.5-second windows
        clusters = []
        sorted_history = sorted(self._entry_history, key=lambda x: x['timestamp'])
        for item in sorted_history:
            placed = False
            for cluster in clusters:
                if (item['timestamp'] - cluster[0]['timestamp']).total_seconds() <= 0.5:
                    cluster.append(item)
                    placed = True
                    break
            if not placed:
                clusters.append([item])
                
        result_vids = []
        logged_groups = getattr(self, '_logged_groups', set())
        if not hasattr(self, '_logged_groups'):
            self._logged_groups = logged_groups
            
        for cluster in clusters:
            cluster_vids = [item['visitor_id'] for item in cluster]
            if len(cluster) >= 2:
                group_key = frozenset(cluster_vids)
                if group_key not in logged_groups:
                    logger.info(f"Group entry detected: {len(cluster)} people entering simultaneously")
                    logged_groups.add(group_key)
                
                # Check if it contains any detection from the current frame
                current_frame_vids = [d.get('visitor_id') for d in zone_dets]
                if any(vid in cluster_vids for vid in current_frame_vids):
                    result_vids.extend(cluster_vids)
                    
        return list(set(result_vids))

    def handle_partial_occlusion(self, detection_confidence: float, track_age_frames: int) -> float:
        """
        Adjusts detection confidence for partially occluded tracks.
        RULE: NEVER drop a detection silently. Low-confidence detections must
        still emit events with confidence field reflecting their actual score.
        """
        if detection_confidence < 0.5 and track_age_frames < 10:
            # Brand new, low confidence — possibly occluded. Do NOT drop.
            # Return as-is but flag in metadata.
            return detection_confidence
            
        if detection_confidence < 0.35:
            # Very low confidence, long track — likely becoming occluded.
            # Degrading gracefully: keep tracking but reduce confidence
            return max(0.20, detection_confidence)
            
        return detection_confidence

def main():
    parser = argparse.ArgumentParser(description="Core CCTV Ingestion & Analytics Pipeline")
    parser.add_argument("--clips-dir", type=str, default="./data/clips", 
                        help="Directory containing video clips")
    parser.add_argument("--output-dir", type=str, default="./data/events", 
                        help="Directory where JSONL logs will be written")
    parser.add_argument("--store-layout-path", type=str, default="./data/store_layout.json", 
                        help="Path to store_layout.json file")
    parser.add_argument("--store-id", type=str, default=None, 
                        help="Store Identifier override")
    parser.add_argument("--fps-process", type=int, default=5, 
                        help="Process frame rates per second (default: 5)")
    parser.add_argument("--device", type=str, default=None, 
                        help="Execution device: 'cuda' or 'cpu'")
                        
    args = parser.parse_args()
    
    # Infer store_id from layout path filename if not specified
    store_id = args.store_id
    if not store_id and os.path.exists(args.store_layout_path):
        filename = os.path.basename(args.store_layout_path)
        store_id, _ = os.path.splitext(filename)
        # Clean naming stub if generic
        if store_id == "store_layout":
            store_id = "STORE_BLR_002"
        elif store_id.startswith("store_layout_"):
            store_id = store_id[len("store_layout_"):]
            
    # Setup default layout if missing
    if not os.path.exists(args.store_layout_path):
        os.makedirs(os.path.dirname(args.store_layout_path), exist_ok=True)
        default_layout = {
            "store_id": "STORE_BLR_002",
            "cameras": {
                "CAM_ENTRY_01": {
                    "homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "zones": {
                        "entrance_lobby": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
                    }
                },
                "CAM_FLOOR_01": {
                    "homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "zones": {
                        "apparel_aisle": [[1000.0, 0.0], [2000.0, 0.0], [2000.0, 1000.0], [1000.0, 1000.0]]
                    }
                },
                "CAM_BILLING_01": {
                    "homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    "zones": {
                        "checkout_queue_01": [[2000.0, 0.0], [3000.0, 0.0], [3000.0, 1000.0], [2000.0, 1000.0]]
                    }
                }
            }
        }
        with open(args.store_layout_path, "w", encoding="utf-8") as f:
            json.dump(default_layout, f, indent=2)
            
    # Create processor and run
    try:
        processor = VideoProcessor(
            store_layout_path=args.store_layout_path,
            store_id=store_id,
            fps_process=args.fps_process,
            device=args.device
        )
        processor.process_all_clips(args.clips_dir, args.output_dir)
    except Exception as e:
        logger.exception("Pipeline execution failed", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
