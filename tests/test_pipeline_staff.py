# PROMPT: We are in store-intelligence/tests/. Write tests for pipeline/staff.py to test the StaffClassifier.
# CHANGES MADE: Created tests/test_pipeline_staff.py with unit tests for StaffClassifier initialization, crop updates, classification cache/fallback logic, and visitor clearing.

import sys
from unittest.mock import MagicMock, patch

# Mock transformers before importing pipeline.staff
mock_clip_model = MagicMock()
mock_clip_processor = MagicMock()

class MockLogits:
    def softmax(self, dim):
        # returns tensor matching staff probability
        # index 0 is staff, index 1 is customer
        import torch
        return [[torch.tensor(0.85), torch.tensor(0.15)]]

mock_outputs = MagicMock()
mock_outputs.logits_per_image = MockLogits()
mock_clip_model.from_pretrained.return_value = mock_clip_model
mock_clip_model.return_value = mock_outputs
mock_clip_processor.from_pretrained.return_value = mock_clip_processor

sys.modules['transformers'] = MagicMock()
sys.modules['transformers'].CLIPModel = mock_clip_model
sys.modules['transformers'].CLIPProcessor = mock_clip_processor

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from pipeline.staff import StaffClassifier

def test_staff_classifier_init():
    classifier = StaffClassifier(confidence_threshold=0.85, min_track_age_seconds=10.0)
    assert classifier.confidence_threshold == 0.85
    assert classifier.min_track_age_seconds == 10.0
    assert classifier.cache == {}
    assert classifier.visitor_crops == {}

def test_staff_classifier_update_crop():
    classifier = StaffClassifier(min_track_age_seconds=5.0)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    bbox = (10, 20, 50, 60)
    now = datetime.now(timezone.utc)
    
    # Update first crop
    classifier.update_crop("VIS_000001", frame, bbox, now, 0.80)
    assert "VIS_000001" in classifier.visitor_first_seen
    assert classifier.best_confidence["VIS_000001"] == 0.80
    assert classifier.visitor_crops["VIS_000001"].shape == (40, 40, 3)

def test_staff_classifier_classify_clip_path():
    classifier = StaffClassifier(confidence_threshold=0.80, min_track_age_seconds=5.0)
    # Ensure model is mocked
    classifier.model = mock_clip_model
    classifier.processor = mock_clip_processor
    
    now = datetime.now(timezone.utc)
    classifier.visitor_first_seen["VIS_clip"] = now
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    classifier.update_crop("VIS_clip", frame, (10, 10, 50, 50), now, 0.85)
    
    # Run classification (using the mocked CLIP path)
    is_staff, conf = classifier.classify(visitor_id="VIS_clip", frame_time=now + timedelta(seconds=6))
    assert is_staff is True
    assert abs(conf - 0.85) < 1e-4

def test_staff_classifier_classify_fallback_logic():
    classifier = StaffClassifier(min_track_age_seconds=5.0)
    classifier.model = None
    classifier.processor = None
    
    # 1. Classify with track_id (backward compatibility fallback)
    res_track = classifier.classify(track_id=123)
    assert res_track is False
    
    # 2. Classify with no visitor_id
    res_none = classifier.classify(visitor_id=None)
    assert res_none == (False, 0.5)
    
    # 3. Classify with visitor_id not in visitor_first_seen
    res_not_seen = classifier.classify(visitor_id="VIS_not_exist")
    assert res_not_seen == (False, 0.5)
    
    # 4. Classify with visitor_id seen but too young (less than min_track_age_seconds)
    now = datetime.now(timezone.utc)
    classifier.visitor_first_seen["VIS_young"] = now
    res_too_young = classifier.classify(visitor_id="VIS_young", frame_time=now + timedelta(seconds=2))
    assert res_too_young == (False, 0.5)
    
    # 5. Classify visitor seen, old enough, but no crop
    res_no_crop = classifier.classify(visitor_id="VIS_young", frame_time=now + timedelta(seconds=6))
    assert res_no_crop == (False, 0.5)

def test_staff_classifier_clear_visitor():
    classifier = StaffClassifier()
    now = datetime.now(timezone.utc)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    
    classifier.update_crop("VIS_000001", frame, (10, 10, 50, 50), now, 0.8)
    classifier.cache["VIS_000001"] = True
    classifier.confidence_cache["VIS_000001"] = 0.9
    
    classifier.clear_visitor("VIS_000001")
    assert "VIS_000001" not in classifier.cache
