#!/usr/bin/env python3
"""
Reset false completion state caused by threading bug.
This script clears the 5692 false "completed" items that were marked as completed
when they actually failed due to the threading import bug.
"""

import os
import sys
from pathlib import Path

# Add youspotter to Python path
sys.path.insert(0, str(Path(__file__).parent))

from youspotter.storage import DB
from youspotter.status import get_status, reset_false_completions, add_recent
import json

def main():
    # Use same DB path as app
    db_path = os.environ.get('YOUSPOTTER_DB', str(Path.cwd() / 'youspotter.db'))
    db = DB(Path(db_path))

    # Setup persistence for status module
    from youspotter import status as st
    def load_snapshot():
        try:
            raw = db.get_setting('status_snapshot') or ''
            return json.loads(raw) if raw else None
        except Exception:
            return None
    def save_snapshot(data: dict):
        try:
            db.set_setting('status_snapshot', json.dumps(data))
        except Exception:
            pass
    st.register_persistence(load_snapshot, save_snapshot)

    print("Current state BEFORE reset:")
    status = get_status()
    queue = status.get('queue', {})
    print(f"  Pending: {len(queue.get('pending', []))}")
    print(f"  Current: {len(queue.get('current', []))}")
    print(f"  Completed: {len(queue.get('completed', []))}")

    completed_items = queue.get('completed', [])
    missing_count = len([item for item in completed_items if item.get('status') == 'missing'])
    downloaded_count = len([item for item in completed_items if item.get('status') == 'downloaded'])
    print(f"  Completed breakdown: {missing_count} failed, {downloaded_count} actually downloaded")

    print("\nResetting false completions...")
    failed_count, actual_count = reset_false_completions()

    print(f"Moved {failed_count} failed items back to pending queue")
    print(f"Kept {actual_count} actual downloads in completed queue")

    add_recent(f"SYSTEM: Reset false completions - moved {failed_count} failed items back to pending", "INFO")

    print("\nCurrent state AFTER reset:")
    status = get_status()
    queue = status.get('queue', {})
    print(f"  Pending: {len(queue.get('pending', []))}")
    print(f"  Current: {len(queue.get('current', []))}")
    print(f"  Completed: {len(queue.get('completed', []))}")

    print("\nReset complete!")

if __name__ == '__main__':
    main()