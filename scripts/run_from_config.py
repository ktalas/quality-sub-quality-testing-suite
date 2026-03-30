"""
Run QOT scoring from a saved config JSON and write results to the database.

Usage:
    python scripts/run_from_config.py <config.json> [name]

Examples:
    python scripts/run_from_config.py qot_config.json
    python scripts/run_from_config.py qot_config.json "Experiment v3 - revenue buckets"
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.caching import get_cached_connection, load_temporal_metrics, load_production_qot
from utils.config import import_config
from engine.scoring import run_scoring
from engine.spread import apply_spread_quality
from engine.writer import write_calculated_qot, save_config


def main(config_path: str, name: str = None):
    # Load config
    with open(config_path) as f:
        config = import_config(f.read(), 'json')
    print(f"Loaded config from {config_path}")
    print(f"  Baseline strategy: {config.get('baseline_strategy', 'quality_table')}")

    # Load data
    df = load_temporal_metrics()
    if df is None:
        print("ERROR: No temporal_metrics.parquet found. Run 'Refresh Data' in the app first.")
        sys.exit(1)
    print(f"  Loaded {len(df):,} company-year records")

    # Load production qot if needed
    production_qot = None
    if config.get('baseline_strategy') == 'qot_table':
        conn = get_cached_connection()
        if conn is None:
            print("ERROR: No database connection. Check DATABASE_URL in .env")
            sys.exit(1)
        production_qot = load_production_qot(conn)
        print(f"  Loaded {len(production_qot):,} production QOT records")

    # Run scoring
    print("Running scoring engine...")
    scored = run_scoring(df, config, production_qot=production_qot)

    print("Applying temporal spreading...")
    scored = apply_spread_quality(scored)

    # Write to DB
    conn = get_cached_connection()
    if conn is None:
        print("ERROR: No database connection. Check DATABASE_URL in .env")
        sys.exit(1)

    print("Writing to database...")
    config_hash, count = write_calculated_qot(scored, config, conn)
    save_config(config, conn, name=name)

    print(f"\nDone! Wrote {count:,} records to calculated_qot")
    print(f"  Config hash: {config_hash}")
    if name:
        print(f"  Config name: {name}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_from_config.py <config.json> [name]")
        sys.exit(1)

    config_path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else None
    main(config_path, name)
