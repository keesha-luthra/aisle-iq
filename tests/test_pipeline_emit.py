# PROMPT: We are in store-intelligence/tests/. Write tests for pipeline/emit.py to cover argparse, retry logic, batching, and error handling.
# CHANGES MADE: Added tests/test_pipeline_emit.py with comprehensive coverage of parse_args, send_batch_with_retry, and emit_events functions.

import os
import sys
import json
import pytest
import httpx
from unittest.mock import patch, MagicMock
from pipeline.emit import parse_args, send_batch_with_retry, emit_events

def test_parse_args():
    with patch("sys.argv", ["emit.py", "--events-dir", "/path/to/events", "--api-url", "http://testapi"]):
        args = parse_args()
        assert args.events_dir == "/path/to/events"
        assert args.api_url == "http://testapi"

def test_send_batch_with_retry_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"accepted": 5, "rejected": 0, "duplicate": 0}
    mock_client.post.return_value = mock_response

    res = send_batch_with_retry(mock_client, "http://endpoint", [{"event_id": "xyz"}])
    assert res == {"accepted": 5, "rejected": 0, "duplicate": 0}
    mock_client.post.assert_called_once()

def test_send_batch_with_retry_500_retries():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=mock_response)
    mock_client.post.return_value = mock_response

    with patch("time.sleep") as mock_sleep:
        res = send_batch_with_retry(mock_client, "http://endpoint", [{"event_id": "xyz"}], max_retries=2)
        assert res is None
        assert mock_client.post.call_count == 3  # Initial + 2 retries
        assert mock_sleep.call_count == 2

def test_send_batch_with_retry_connection_error():
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.RequestError("Connection refused")

    with patch("time.sleep") as mock_sleep:
        res = send_batch_with_retry(mock_client, "http://endpoint", [{"event_id": "xyz"}], max_retries=1)
        assert res is None
        assert mock_client.post.call_count == 2  # Initial + 1 retry
        assert mock_sleep.call_count == 1

def test_emit_events_no_dir():
    with patch("builtins.print") as mock_print:
        emit_events("non_existent_dir_12345", "http://endpoint")
        mock_print.assert_any_call("Error: Directory 'non_existent_dir_12345' does not exist.")

def test_emit_events_empty_dir(tmp_path):
    with patch("builtins.print") as mock_print:
        emit_events(str(tmp_path), "http://endpoint")
        mock_print.assert_any_call("No event log files (.jsonl) found.")

def test_emit_events_processing(tmp_path):
    # Create valid and invalid jsonl files
    file1 = tmp_path / "events1.jsonl"
    import uuid
    from datetime import datetime, timezone
    
    valid_event = {
        "event_id": str(uuid.uuid4()),
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_01",
        "visitor_id": "VIS_abc123",
        "event_type": "ENTRY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.95
    }
    
    invalid_event_str = "not-json-line\n"
    
    with open(file1, "w", encoding="utf-8") as f:
        f.write(json.dumps(valid_event) + "\n")
        f.write(invalid_event_str)

    mock_client_instance = MagicMock()
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"accepted": 1, "rejected": 0, "duplicate": 0}
    mock_client_instance.post.return_value = mock_response

    with patch("httpx.Client", return_value=mock_client_instance):
        with patch("builtins.print") as mock_print:
            emit_events(str(tmp_path), "http://endpoint")
            # Verify we scan file, find 1 valid, 1 invalid line
            mock_print.assert_any_call("\n=== Event Emitter Ingestion Summary ===")
