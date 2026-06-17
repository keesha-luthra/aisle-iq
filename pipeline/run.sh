#!/usr/bin/env bash
set -e

# Reads CLIPS_DIR from $1 or defaults to ./data/clips
CLIPS_DIR="${1:-./data/clips}"

# Reads OUTPUT_DIR from $2 or defaults to ./data/events
OUTPUT_DIR="${2:-./data/events}"

# Reads LAYOUT_PATH from $3 or defaults to ./data/store_layout.json
LAYOUT_PATH="${3:-./data/store_layout.json}"

# Activates virtualenv if present
if [ -d ".venv" ]; then
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    fi
elif [ -d "venv" ]; then
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif [ -f "venv/Scripts/activate" ]; then
        source venv/Scripts/activate
    fi
fi

# Runs detect pipeline
python -m pipeline.detect --clips-dir "$CLIPS_DIR" --output-dir "$OUTPUT_DIR" --store-layout-path "$LAYOUT_PATH"

# Print follow-up instructions
echo "Events written to $OUTPUT_DIR. Now POST to API with:"
echo "python -m pipeline.emit --events-dir $OUTPUT_DIR --api-url http://localhost:8000"
