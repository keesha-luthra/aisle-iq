# PROMPT: We are in store-intelligence/tests/. Write the full pipeline and schema test suite. Test class TestStoreEventSchema, TestStateMachine, TestEmbeddingExtractor, and TestZoneMapper.
# CHANGES MADE: Created TestStoreEventSchema, TestStateMachine, TestEmbeddingExtractor, and TestZoneMapper test classes with complete validation coverage, and added required prompt headers.

import pytest
import numpy as np
import json
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError
from unittest.mock import MagicMock

from app.schemas import StoreEvent
from pipeline.state_machine import PipelineStateMachine
from pipeline.tracker import EmbeddingExtractor
from pipeline.zones import ZoneMapper

class TestStoreEventSchema:
    def test_valid_event_passes_validation(self, sample_event):
        model = StoreEvent.model_validate(sample_event)
        assert model.store_id == sample_event["store_id"]
        assert model.confidence == sample_event["confidence"]

    def test_zone_enter_requires_zone_id(self, sample_event):
        sample_event["event_type"] = "ZONE_ENTER"
        sample_event["zone_id"] = None
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_billing_join_requires_queue_depth(self, sample_event):
        sample_event["event_type"] = "BILLING_QUEUE_JOIN"
        sample_event["metadata"] = {}
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_confidence_must_be_between_0_and_1(self, sample_event):
        # 1.01 must fail
        sample_event["confidence"] = 1.01
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)
            
        # -0.1 must fail
        sample_event["confidence"] = -0.1
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_naive_timestamp_raises_error(self, sample_event):
        # Naive datetime must fail (needs timezone)
        sample_event["timestamp"] = datetime.now().replace(tzinfo=None).isoformat()
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_visitor_id_pattern_enforced(self, sample_event):
        # "invalid_id" must fail
        sample_event["visitor_id"] = "invalid_id"
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)
            
        # "VIS_abc123" must pass
        sample_event["visitor_id"] = "VIS_abc123"
        model = StoreEvent.model_validate(sample_event)
        assert model.visitor_id == "VIS_abc123"

    def test_event_id_must_be_uuid(self, sample_event):
        # "not-a-uuid" must fail
        sample_event["event_id"] = "not-a-uuid"
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_dwell_ms_cannot_be_negative(self, sample_event):
        sample_event["dwell_ms"] = -10
        with pytest.raises(ValidationError):
            StoreEvent.model_validate(sample_event)

    def test_metadata_defaults_are_correct(self, sample_event):
        if "metadata" in sample_event:
            del sample_event["metadata"]
        model = StoreEvent.model_validate(sample_event)
        assert model.metadata.queue_depth is None
        assert model.metadata.sku_zone is None
        assert model.metadata.session_seq == 0


class TestStateMachine:
    def test_entry_event_emitted_on_new_visitor(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.return_value = True
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=datetime.now(timezone.utc)
        )
        assert len(events) >= 2
        event_types = [e["event_type"] for e in events]
        assert "ENTRY" in event_types
        assert "ZONE_ENTER" in event_types

    def test_zone_enter_exit_sequence(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.side_effect = lambda z: z == "Entrance"
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        now = datetime.now(timezone.utc)
        
        sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now
        )
        
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Aisle_1",
            is_staff=False,
            confidence=0.95,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now + timedelta(seconds=10)
        )
        assert len(events) == 2
        assert events[0]["event_type"] == "ZONE_EXIT"
        assert events[0]["zone_id"] == "Entrance"
        assert events[0]["dwell_ms"] == 10000
        assert events[1]["event_type"] == "ZONE_ENTER"
        assert events[1]["zone_id"] == "Aisle_1"

    def test_zone_dwell_emitted_after_threshold(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.side_effect = lambda z: z == "Entrance"
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper, zone_dwell_seconds=10.0)
        now = datetime.now(timezone.utc)
        
        sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now
        )
        
        # Within threshold (5 seconds)
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now + timedelta(seconds=5)
        )
        assert len(events) == 0
        
        # Beyond threshold (11 seconds)
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now + timedelta(seconds=11)
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "ZONE_DWELL"
        assert events[0]["dwell_ms"] == 11000

    def test_no_duplicate_events_on_same_zone(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.side_effect = lambda z: z == "Entrance"
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        now = datetime.now(timezone.utc)
        
        sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now
        )
        
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01_ENTRY",
            timestamp=now + timedelta(seconds=2)
        )
        assert len(events) == 0

    def test_reentry_emits_reentry_event_not_entry(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.return_value = True
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        
        events = sm.update(
            visitor_id="VIS_abc123",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01",
            timestamp=datetime.now(timezone.utc),
            is_reentry=True
        )
        event_types = [e["event_type"] for e in events]
        assert "REENTRY" in event_types
        assert "ENTRY" not in event_types

    def test_exit_clears_visitor_state(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.return_value = True
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        visitor_id = "VIS_abc123"
        
        sm.update(
            visitor_id=visitor_id,
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01",
            timestamp=datetime.now(timezone.utc)
        )
        assert visitor_id in sm.states
        
        events = sm.handle_exit(
            visitor_id=visitor_id,
            camera_id="CAM_EXIT",
            frame_time=datetime.now(timezone.utc),
            store_id="STORE_TEST"
        )
        event_types = [e["event_type"] for e in events]
        assert "EXIT" in event_types
        assert visitor_id not in sm.states

    def test_empty_period_evicts_stale_visitors(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.return_value = True
        mock_mapper.is_billing_zone.return_value = False
        mock_mapper.get_zone_sku.return_value = None
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        now = datetime.now(timezone.utc)
        visitor_id = "VIS_abc123"
        
        sm.update(
            visitor_id=visitor_id,
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01",
            timestamp=now
        )
        
        # 6 seconds later, call handle_empty_period
        sm.handle_empty_period(now + timedelta(seconds=6), "STORE_TEST")
        events = sm.flush_pending()
        event_types = [e["event_type"] for e in events]
        assert "EXIT" in event_types
        assert visitor_id not in sm.states

    def test_group_entry_produces_individual_events(self):
        mock_mapper = MagicMock()
        mock_mapper.is_entry_zone.return_value = True
        mock_mapper.is_billing_zone.return_value = False
        
        sm = PipelineStateMachine(zone_mapper=mock_mapper)
        now = datetime.now(timezone.utc)
        
        evs1 = sm.update(
            visitor_id="VIS_111111",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01",
            timestamp=now
        )
        evs2 = sm.update(
            visitor_id="VIS_222222",
            zone_id="Entrance",
            is_staff=False,
            confidence=0.9,
            store_id="STORE_TEST",
            camera_id="CAM_01",
            timestamp=now
        )
        assert len(evs1) >= 2
        assert len(evs2) >= 2
        assert sm.states["VIS_111111"].has_entered is True
        assert sm.states["VIS_222222"].has_entered is True


class TestEmbeddingExtractor:
    def test_extract_returns_correct_shape(self):
        extractor = EmbeddingExtractor(device="cpu")
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        bbox = (10, 10, 100, 100)
        emb = extractor.extract(frame, bbox)
        assert emb.shape == (512,)

    def test_extract_returns_normalized_vector(self):
        extractor = EmbeddingExtractor(device="cpu")
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        frame[10:100, 10:100] = 255
        bbox = (10, 10, 100, 100)
        emb = extractor.extract(frame, bbox)
        norm = np.linalg.norm(emb)
        if norm > 0:
            assert abs(norm - 1.0) < 1e-4

    def test_extract_handles_invalid_bbox_gracefully(self):
        extractor = EmbeddingExtractor(device="cpu")
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        bbox = (400, 400, 500, 500)
        emb = extractor.extract(frame, bbox)
        assert emb.shape == (512,)
        assert np.all(emb == 0.0)

    def test_cosine_same_image_high_similarity(self):
        extractor = EmbeddingExtractor(device="cpu")
        frame = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
        bbox = (10, 10, 100, 100)
        emb1 = extractor.extract(frame, bbox)
        emb2 = extractor.extract(frame, bbox)
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        if norm1 > 0 and norm2 > 0:
            similarity = dot_product / (norm1 * norm2)
            assert similarity > 0.9


class TestZoneMapper:
    def test_point_in_zone_returns_zone_id(self, tmp_path):
        layout = {
            "store_id": "STORE_TEST",
            "cameras": {},
            "zones": [
                {
                    "zone_id": "Aisle_1",
                    "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
                }
            ]
        }
        layout_file = tmp_path / "store_layout_test.json"
        with open(layout_file, "w", encoding="utf-8") as f:
            json.dump(layout, f)
            
        mapper = ZoneMapper(str(layout_file))
        assert mapper.get_zone((5.0, 5.0), "CAM_01") == "Aisle_1"

    def test_point_outside_all_zones_returns_none(self, tmp_path):
        layout = {
            "store_id": "STORE_TEST",
            "cameras": {},
            "zones": [
                {
                    "zone_id": "Aisle_1",
                    "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
                }
            ]
        }
        layout_file = tmp_path / "store_layout_test.json"
        with open(layout_file, "w", encoding="utf-8") as f:
            json.dump(layout, f)
            
        mapper = ZoneMapper(str(layout_file))
        assert mapper.get_zone((15.0, 15.0), "CAM_01") is None

    def test_billing_zone_detection(self, tmp_path):
        layout = {
            "store_id": "STORE_TEST",
            "cameras": {},
            "zones": [
                {
                    "zone_id": "BILLING_ZONE_01",
                    "polygon": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
                }
            ]
        }
        layout_file = tmp_path / "store_layout_test.json"
        with open(layout_file, "w", encoding="utf-8") as f:
            json.dump(layout, f)
            
        mapper = ZoneMapper(str(layout_file))
        assert mapper.is_billing_zone("BILLING_ZONE_01") is True
        assert mapper.is_billing_zone("Aisle_1") is False

    def test_missing_layout_uses_fallback(self):
        mapper = ZoneMapper("non_existent_layout.json")
        assert "FALLBACK" in mapper.store_id
        assert mapper.is_billing_zone("BILLING") is True
