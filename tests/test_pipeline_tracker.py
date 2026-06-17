# PROMPT: We are in store-intelligence/tests/. Write tests for pipeline/tracker.py to test the VisitorTracker (ReIDTracker).
# CHANGES MADE: Created tests/test_pipeline_tracker.py with unit tests for VisitorTracker registration, reentry matching, exit marking, and active visitor retrieval.

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from pipeline.tracker import VisitorTracker, EmbeddingExtractor

def test_visitor_tracker_init():
    tracker = VisitorTracker(reid_threshold=0.8, reentry_window_seconds=100)
    assert tracker.reid_threshold == 0.8
    assert tracker.reentry_window_seconds == 100
    assert tracker.track_to_visitor == {}
    assert tracker.visitor_embeddings == {}
    assert tracker.visitor_exit_times == {}

def test_visitor_tracker_new_and_cached_visitor():
    tracker = VisitorTracker(reid_threshold=0.75, reentry_window_seconds=300)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    now = datetime.now(timezone.utc)
    
    # 1. Register a new visitor
    vid1, reentry1 = tracker.get_visitor_id(track_id=1, frame=frame, bbox=bbox, frame_time=now)
    assert vid1.startswith("VIS_")
    assert reentry1 is False
    assert tracker.track_to_visitor[1] == vid1
    
    # 2. Query again for the same track_id, should return cached mapping directly
    vid2, reentry2 = tracker.get_visitor_id(track_id=1, frame=frame, bbox=bbox, frame_time=now + timedelta(seconds=1))
    assert vid2 == vid1
    assert reentry2 is False

def test_visitor_tracker_reentry():
    tracker = VisitorTracker(reid_threshold=0.75, reentry_window_seconds=300)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    now = datetime.now(timezone.utc)
    
    # Register new visitor
    vid1, _ = tracker.get_visitor_id(track_id=1, frame=frame, bbox=bbox, frame_time=now)
    
    # Mark exited
    tracker.mark_exited(vid1, now + timedelta(seconds=10))
    assert vid1 in tracker.visitor_exit_times
    assert 1 not in tracker.track_to_visitor
    
    # Reenter with the same appearance (same frame/bbox produces same embedding) within window (e.g. 50 seconds elapsed)
    vid2, reentry = tracker.get_visitor_id(track_id=2, frame=frame, bbox=bbox, frame_time=now + timedelta(seconds=60))
    assert vid2 == vid1
    assert reentry is True
    assert vid1 not in tracker.visitor_exit_times
    assert tracker.track_to_visitor[2] == vid1

def test_visitor_tracker_reentry_out_of_window():
    tracker = VisitorTracker(reid_threshold=0.75, reentry_window_seconds=10)
    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    now = datetime.now(timezone.utc)
    
    # Register new visitor
    vid1, _ = tracker.get_visitor_id(track_id=1, frame=frame, bbox=bbox, frame_time=now)
    tracker.mark_exited(vid1, now + timedelta(seconds=2))
    
    # Reenter after 15 seconds (exceeding reentry_window_seconds=10)
    vid2, reentry = tracker.get_visitor_id(track_id=2, frame=frame, bbox=bbox, frame_time=now + timedelta(seconds=20))
    assert vid2 != vid1
    assert reentry is False

def test_visitor_tracker_reentry_low_similarity():
    tracker = VisitorTracker(reid_threshold=0.99, reentry_window_seconds=300)
    
    # Setup tracker with dummy data
    vid = "VIS_dummy1"
    tracker.visitor_embeddings[vid] = np.ones(512, dtype=np.float32) / np.sqrt(512)
    tracker.visitor_exit_times[vid] = datetime.now(timezone.utc)
    
    # Construct a slightly different embedding by passing random frame crop
    frame = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
    bbox = (10, 10, 100, 100)
    
    # Reenter, should not match because reid_threshold is too high (0.99)
    new_vid, reentry = tracker.get_visitor_id(track_id=5, frame=frame, bbox=bbox, frame_time=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert new_vid != vid
    assert reentry is False

def test_visitor_tracker_get_active_visitors():
    tracker = VisitorTracker()
    now = datetime.now(timezone.utc)
    tracker.visitor_embeddings["VIS_1"] = np.ones(512)
    tracker.visitor_embeddings["VIS_2"] = np.ones(512)
    
    tracker.visitor_exit_times["VIS_1"] = now
    
    active = tracker.get_active_visitors()
    assert "VIS_2" in active
    assert "VIS_1" not in active
