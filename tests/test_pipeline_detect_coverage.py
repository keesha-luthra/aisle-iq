# PROMPT: Write unit tests for pipeline/detect.py to cover _parse_clip_start_time filename variations, process_all_clips flow, and main CLI argument parser execution.
# CHANGES MADE: Created test_pipeline_detect_coverage.py with direct calls to parsing functions, mocked directory structure processing, and mock sys.argv CLI parsing tests.

import pytest
import os
import sys
import tempfile
from datetime import datetime, timezone
from pipeline.detect import VideoProcessor, main

@pytest.fixture
def dummy_layout(tmp_path):
    layout_file = tmp_path / "store_layout.json"
    layout_file.write_text('{"store_id": "STORE_TEST", "cameras": {}}', encoding="utf-8")
    return str(layout_file)

def test_parse_clip_start_time_formats(dummy_layout):
    vp = VideoProcessor(store_layout_path=dummy_layout, device="cpu")
    
    # 1. Test YYYYMMDD_HHMMSS format
    t1 = vp._parse_clip_start_time("CAM_01_20260303_142210.mp4")
    assert t1.year == 2026
    assert t1.month == 3
    assert t1.day == 3
    assert t1.hour == 14
    assert t1.minute == 22
    assert t1.second == 10
    assert t1.tzinfo == timezone.utc
    
    # 2. Test YYYYMMDDTHHMMSS format
    t2 = vp._parse_clip_start_time("CAM_01_20260303T142210.mp4")
    assert t2.year == 2026
    assert t2.month == 3
    assert t2.hour == 14
    
    # 3. Test fallback
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_name = tmp.name
    try:
        t3 = vp._parse_clip_start_time(tmp_name)
        assert isinstance(t3, datetime)
    finally:
        os.remove(tmp_name)

def test_process_all_clips_empty_or_no_clips(dummy_layout):
    vp = VideoProcessor(store_layout_path=dummy_layout, device="cpu")
    
    # Non-existent source dir
    vp.process_all_clips("non_existent_dir", "output_dir")
    
    # Empty source dir
    with tempfile.TemporaryDirectory() as tmp_src:
        with tempfile.TemporaryDirectory() as tmp_out:
            vp.process_all_clips(tmp_src, tmp_out)
            assert len(os.listdir(tmp_out)) == 0

def test_main_cli_execution(monkeypatch, dummy_layout):
    # Mock VideoProcessor process_all_clips
    mock_run_called = False
    def mock_process_all_clips(self, clips_dir, output_dir):
        nonlocal mock_run_called
        mock_run_called = True

    monkeypatch.setattr(VideoProcessor, "process_all_clips", mock_process_all_clips)
    
    # Mock sys.argv
    test_args = [
        "detect.py",
        "--clips-dir", "./dummy_clips",
        "--output-dir", "./dummy_events",
        "--store-layout-path", dummy_layout,
        "--store-id", "STORE_MOCK_1"
    ]
    monkeypatch.setattr(sys, "argv", test_args)
    
    main()
    assert mock_run_called is True
