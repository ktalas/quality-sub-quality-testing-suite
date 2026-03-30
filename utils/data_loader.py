"""
Data loading utilities with error handling.
"""
import os
from datetime import datetime
from utils.caching import load_temporal_metrics


def get_temporal_metrics():
    """Load temporal metrics, returning None if not yet built."""
    return load_temporal_metrics()


def get_data_status() -> dict:
    """Check status of the local parquet data file."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "temporal_metrics.parquet")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {"exists": False, "last_modified": None, "record_count": 0}

    mtime = os.path.getmtime(path)
    last_modified = datetime.fromtimestamp(mtime)

    # Get row count without loading full df
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    record_count = pf.metadata.num_rows

    return {
        "exists": True,
        "last_modified": last_modified,
        "record_count": record_count,
    }
