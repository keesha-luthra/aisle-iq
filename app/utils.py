import json
from pathlib import Path

def load_layout(store_id: str) -> dict:
    """Load the JSON layout file for the given store ID.
    Expected filename pattern: data/store_layout_{store_id}.json
    """
    layout_path = Path(__file__).parent.parent / "data" / f"store_layout_{store_id}.json"
    if not layout_path.is_file():
        raise FileNotFoundError(f"Layout file not found for store_id {store_id}: {layout_path}")
    with layout_path.open("r", encoding="utf-8") as f:
        return json.load(f)
