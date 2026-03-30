"""
Write scored QOT results to the database.
Creates calculated_qot and qot_configs tables if they don't exist.
"""
import hashlib
import json
import pandas as pd
from datetime import datetime
from psycopg2.extras import execute_values


def compute_config_hash(config: dict) -> str:
    """Deterministic SHA-256 hash of config for traceability.
    Skips runtime-only keys (prefixed with '_').
    """
    serializable = {k: v for k, v in config.items() if not k.startswith('_')}
    config_str = json.dumps(serializable, sort_keys=True, default=str)
    return hashlib.sha256(config_str.encode()).hexdigest()


def write_calculated_qot(scored_df: pd.DataFrame, config: dict, conn,
                         replace_existing: bool = True):
    """Write scored DataFrame to calculated_qot SQL table.

    Args:
        scored_df: DataFrame with calculated_qot column (output of scoring pipeline)
        config: The config dict used for scoring
        conn: psycopg2 connection
        replace_existing: If True, delete previous results for this config_hash first

    Returns:
        (config_hash, record_count) tuple
    """
    config_hash = compute_config_hash(config)
    baseline = config.get('baseline_strategy', 'quality_table')
    now = datetime.now()

    cur = conn.cursor()

    # Create table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS calculated_qot (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            calculated_qot INTEGER NOT NULL CHECK (calculated_qot BETWEEN 1 AND 5),
            last_rule_applied VARCHAR(100),
            baseline_strategy VARCHAR(50),
            config_hash VARCHAR(64),
            run_timestamp TIMESTAMP DEFAULT NOW(),
            UNIQUE (company_id, year, config_hash)
        )
    """)

    # Create indexes (IF NOT EXISTS supported in pg 9.5+)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_calc_qot_company_year
        ON calculated_qot(company_id, year)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_calc_qot_config
        ON calculated_qot(config_hash)
    """)

    if replace_existing:
        cur.execute("DELETE FROM calculated_qot WHERE config_hash = %s", (config_hash,))

    # Prepare values
    records = scored_df[['company_id', 'year', 'calculated_qot', 'last_rule_applied']].copy()
    values = [
        (int(row.company_id), int(row.year), int(row.calculated_qot),
         str(row.last_rule_applied) if pd.notna(row.last_rule_applied) else None,
         baseline, config_hash, now)
        for row in records.itertuples()
    ]

    execute_values(cur, """
        INSERT INTO calculated_qot
            (company_id, year, calculated_qot, last_rule_applied,
             baseline_strategy, config_hash, run_timestamp)
        VALUES %s
        ON CONFLICT (company_id, year, config_hash) DO UPDATE SET
            calculated_qot = EXCLUDED.calculated_qot,
            last_rule_applied = EXCLUDED.last_rule_applied,
            run_timestamp = EXCLUDED.run_timestamp
    """, values)

    conn.commit()
    return config_hash, len(values)


def save_config(config: dict, conn, name: str = None, match_rate: float = None):
    """Save config JSON to qot_configs table for reference.

    Returns:
        config_hash
    """
    config_hash = compute_config_hash(config)
    serializable = {k: v for k, v in config.items() if not k.startswith('_')}

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS qot_configs (
            config_hash VARCHAR(64) PRIMARY KEY,
            config_json JSONB NOT NULL,
            name VARCHAR(200),
            match_rate NUMERIC(5,2),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        INSERT INTO qot_configs (config_hash, config_json, name, match_rate)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (config_hash) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, qot_configs.name),
            match_rate = COALESCE(EXCLUDED.match_rate, qot_configs.match_rate)
    """, (config_hash, json.dumps(serializable, default=str), name, match_rate))

    conn.commit()
    return config_hash
