# PROMPT: We are in store-intelligence/tests/. Write tests for pipeline enhancements including queue depth estimation, group entry detection, partial occlusion handling, and empty period synthetic exits.
# CHANGES MADE: Created test_pipeline_enhancements.py with VideoProcessor queue depth, group entry, partial occlusion, and PipelineStateMachine empty period tests.
import pytest
import logging
from datetime import datetime, timezone, timedelta
from pipeline.detect import VideoProcessor
from pipeline.state_machine import PipelineStateMachine, VisitorState

# Mock layout path for VideoProcessor initialization
MOCK_LAYOUT_CONTENT = """{
  "store_id": "STORE_TEST_01",
  "cameras": {
    "CAM_ENTRY_01": {
      "homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
      "zones": {
        "entrance_lobby": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
      }
    },
    "CAM_BILLING_01": {
      "homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
      "zones": {
        "checkout_queue_01": [[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0]]
      }
    }
  },
  "zones": [
    {
      "zone_id": "entrance_lobby",
      "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    },
    {
      "zone_id": "checkout_queue_01",
      "polygon": [[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0]]
    }
  ]
}"""

@pytest.fixture
def store_layout_file(tmp_path):
    layout_path = tmp_path / "store_layout.json"
    layout_path.write_text(MOCK_LAYOUT_CONTENT, encoding="utf-8")
    return str(layout_path)

@pytest.fixture
def video_processor(store_layout_file, monkeypatch):
    # Mock VideoProcessor.__init__ to avoid loading heavy YOLO and ReID models in test
    def mock_init(self, store_layout_path: str, store_id: str | None = None, 
                  fps_process: int = 5, device: str | None = None):
        self.store_layout = {
            "store_id": "STORE_TEST_01"
        }
        self.store_id = store_id or "STORE_TEST_01"
        self.fps_process = fps_process
        self.device = "cpu"
        self.track_ages = {}
        
        # We only need ZoneMapper for testing
        from pipeline.zones import ZoneMapper
        self.zone_mapper = ZoneMapper(store_layout_path)

    monkeypatch.setattr(VideoProcessor, "__init__", mock_init)
    processor = VideoProcessor(store_layout_path=store_layout_file)
    return processor

def test_estimate_queue_depth(video_processor):
    billing_detections = [
        {"bbox": (21.0, 1.0, 25.0, 5.0), "visitor_id": "VIS_01", "confidence": 0.9, "is_staff": False},
        {"bbox": (22.0, 1.0, 26.0, 5.0), "visitor_id": "VIS_02", "confidence": 0.85, "is_staff": True},
        {"bbox": (23.0, 1.0, 27.0, 5.0), "visitor_id": "VIS_03", "confidence": 0.7, "is_staff": False},
    ]
    
    depth = video_processor.estimate_queue_depth(billing_detections)
    assert depth == 2

def test_handle_group_entry(video_processor, monkeypatch):
    ts1 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = ts1 + timedelta(seconds=0.2)
    ts3 = ts1 + timedelta(seconds=0.4)
    ts4 = ts1 + timedelta(seconds=1.5)  # Outside the 0.5s window
    
    frame_detections = [
        {"visitor_id": "VIS_A", "zone_id": "entrance_lobby", "timestamp": ts1},
        {"visitor_id": "VIS_B", "zone_id": "entrance_lobby", "timestamp": ts2},
        {"visitor_id": "VIS_C", "zone_id": "entrance_lobby", "timestamp": ts3},
        {"visitor_id": "VIS_D", "zone_id": "entrance_lobby", "timestamp": ts4},
    ]
    
    # Mock logger info call
    logged_messages = []
    def mock_log_info(msg, *args, **kwargs):
        logged_messages.append(msg)
    monkeypatch.setattr("pipeline.detect.logger.info", mock_log_info)
    
    # Process group entries
    # We expect a group of A, B, C to be detected
    group_vids = video_processor.handle_group_entry(frame_detections, "entrance_lobby")
    
    # Verify the logs show a group entry
    assert any("Group entry detected: 3 people entering simultaneously" in msg for msg in logged_messages)
    
    # VIS_A, VIS_B, VIS_C should be part of the returned group vids
    assert "VIS_A" in group_vids
    assert "VIS_B" in group_vids
    assert "VIS_C" in group_vids
    # VIS_D should not be in the group since its interval is > 0.5s from the others
    assert "VIS_D" not in group_vids

def test_handle_partial_occlusion(video_processor):
    # Case 1: Brand new, low confidence — possibly occluded
    conf1 = video_processor.handle_partial_occlusion(detection_confidence=0.45, track_age_frames=5)
    assert conf1 == 0.45
    
    # Case 2: Very low confidence, long track — likely becoming occluded
    conf2 = video_processor.handle_partial_occlusion(detection_confidence=0.25, track_age_frames=15)
    assert conf2 == 0.25  # degraded gracefully: max(0.20, 0.25) = 0.25
    
    # Case 3: Extremely low confidence, long track — degraded to max(0.20, confidence)
    conf3 = video_processor.handle_partial_occlusion(detection_confidence=0.15, track_age_frames=15)
    assert conf3 == 0.20
    
    # Case 4: High confidence, long track
    conf4 = video_processor.handle_partial_occlusion(detection_confidence=0.85, track_age_frames=15)
    assert conf4 == 0.85

def test_handle_empty_period():
    sm = PipelineStateMachine()
    ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Simulate a visitor state
    visitor_id = "VIS_1"
    sm.states[visitor_id] = VisitorState(
        visitor_id=visitor_id,
        store_id="STORE_01",
        is_staff=False,
        entry_time=ts,
        zone_entry_time=ts,
        last_seen_time=ts
    )
    
    # 1. Period with no update but <= 5 seconds (say, 3 seconds)
    ts_soon = ts + timedelta(seconds=3)
    sm.handle_empty_period(ts_soon, "STORE_01")
    assert visitor_id in sm.states  # Should still be present
    assert len(sm.pending_events) == 0
    
    # 2. Period with no update > 5 seconds (say, 6 seconds)
    ts_late = ts + timedelta(seconds=6)
    sm.handle_empty_period(ts_late, "STORE_01")
    assert visitor_id not in sm.states  # Should have exited
    assert len(sm.pending_events) > 0
    
    # Verify synthetic EXIT event was generated
    events = sm.flush_pending()
    exit_events = [e for e in events if e["event_type"] == "EXIT"]
    assert len(exit_events) == 1
    assert exit_events[0]["visitor_id"] == visitor_id
    assert exit_events[0]["camera_id"] == "CAM_EMPTY_PERIOD"
