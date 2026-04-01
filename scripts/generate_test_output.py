"""
Generate spec-aligned QOT testing output for Matt's review.

Produces 3 CSVs:
  Tab 1: Changes to Q5 (promoted to or demoted from Q5)
  Tab 2: Confirm Hot + Iconic Designations
  Tab 3: All Other Quality Changes

Usage:
    python scripts/generate_test_output.py [--output-dir ./output]
"""
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv()

from utils.config import SPEC_ALIGNED_CONFIG, ALL_NAMED_VCS, DEFAULT_TIER_1_VCS
from engine.scoring import run_scoring
from engine.writer import write_calculated_qot, save_config


def get_connection():
    """Get DB connection without Streamlit dependency."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)
    return psycopg2.connect(database_url)


def load_temporal_metrics():
    """Load temporal metrics parquet."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "temporal_metrics.parquet")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        print("ERROR: No temporal_metrics.parquet found. Run 'Refresh Data' in the app first.")
        sys.exit(1)
    return pd.read_parquet(path)


def load_production_qot(conn):
    """Load production QOT table."""
    return pd.read_sql("SELECT company_id, year, qot FROM qot", conn)


def load_manual_overrides(conn):
    """Load manual quality overrides where source = 'user'.
    Uses company_quality_details() function which returns JSON with score and source.
    """
    query = """
    SELECT co.company_id, co.company_name,
           company_quality_details(co.company_id) as quality_details
    FROM companies co
    WHERE co.delete IS NOT TRUE
    """
    df = pd.read_sql(query, conn)

    if len(df) == 0:
        return pd.DataFrame(columns=['company_id', 'manual_quality'])

    # Parse JSON quality_details
    overrides = []
    for _, row in df.iterrows():
        details = row['quality_details']
        if details is None:
            continue
        if isinstance(details, str):
            import json as _json
            try:
                details = _json.loads(details)
            except (ValueError, TypeError):
                continue
        if isinstance(details, dict) and details.get('source') == 'user':
            score = details.get('score')
            if score is not None and 1 <= int(score) <= 5:
                overrides.append({
                    'company_id': row['company_id'],
                    'manual_quality': int(score),
                })

    if not overrides:
        return pd.DataFrame(columns=['company_id', 'manual_quality'])

    return pd.DataFrame(overrides)


SOFTWARE_SECTORS = ('Internet', 'Software (non-internet/mobile)')


def load_companies_info(conn):
    """Load company metadata for output."""
    return pd.read_sql("""
        SELECT company_id, company_name, quality_score, sub_quality, mosaic_score, cbi_sector
        FROM companies
        WHERE delete = false OR delete IS NULL
    """, conn)


def filter_software(df, companies_df):
    """Filter to software companies only (Internet + Software sectors)."""
    sw_ids = set(companies_df[
        companies_df['cbi_sector'].isin(SOFTWARE_SECTORS)
    ]['company_id'].unique())
    return df[df['company_id'].isin(sw_ids)]


def run_spec_scoring(df, conn):
    """Run scoring with SPEC_ALIGNED_CONFIG."""
    config = SPEC_ALIGNED_CONFIG.copy()

    # Disable current-year override for pure model output
    # Overrides will be layered in after Matt reviews the base model
    config['enable_current_year_override'] = False
    print("  Manual overrides: disabled (pure model output)")

    # Run scoring (no production_qot needed since baseline is mosaic_only)
    scored = run_scoring(df, config)
    return scored, config


def generate_outputs(scored_df, conn, output_dir):
    """Generate the 3 test output CSVs."""
    os.makedirs(output_dir, exist_ok=True)

    # Load production QOT for comparison
    prod = load_production_qot(conn)
    prod = prod.rename(columns={'qot': 'production_qot'})
    prod['year'] = prod['year'].astype(int)
    prod['production_qot'] = prod['production_qot'].astype(int)

    # Load company info
    companies = load_companies_info(conn)

    # Get most recent year per company for current-state comparison
    latest_year = scored_df['year'].max()

    # Merge scored with production
    compare_cols = ['company_id', 'year', 'calculated_qot', 'calculated_sub_quality',
                    'segment', 'company_name', 'last_rule_applied', 'mosaic_score']
    available = [c for c in compare_cols if c in scored_df.columns]
    merged = scored_df[available].merge(prod, on=['company_id', 'year'], how='inner')
    merged['delta'] = merged['calculated_qot'] - merged['production_qot']
    merged['direction'] = np.where(
        merged['delta'] > 0, 'Promoted',
        np.where(merged['delta'] < 0, 'Demoted', 'No Change')
    )

    # Enrich with sub_quality from companies table
    sq_map = companies[['company_id', 'sub_quality']].drop_duplicates()
    merged = merged.merge(sq_map, on='company_id', how='left')

    # Filter to software companies only
    merged = filter_software(merged, companies)
    print(f"  Filtered to {merged['company_id'].nunique()} software companies")

    # Focus on latest year per company for all tabs
    latest = merged.sort_values('year').groupby('company_id').last().reset_index()

    # --- Tab 1: Changes to Q5 ---
    # Companies where Q5 status changed in latest year vs production
    q5_changes = latest[
        ((latest['calculated_qot'] == 5) & (latest['production_qot'] != 5)) |
        ((latest['calculated_qot'] != 5) & (latest['production_qot'] == 5))
    ].copy()
    q5_changes = q5_changes.sort_values('delta', key=abs, ascending=False)

    tab1 = q5_changes[[
        'company_id', 'company_name', 'segment', 'mosaic_score',
        'sub_quality', 'production_qot', 'calculated_qot', 'delta',
        'direction', 'last_rule_applied'
    ]].copy()
    tab1_path = os.path.join(output_dir, 'Tab 1 - Changes to Q5.csv')
    tab1.to_csv(tab1_path, index=False)
    print(f"  Tab 1: {len(tab1)} companies with Q5 changes -> {tab1_path}")

    q5_company_ids = set(q5_changes['company_id'].unique())

    # --- Tab 2: Sub-Quality Designations ---
    # Model now auto-assigns calculated_sub_quality. Compare against current DB values.
    has_designation = latest[
        latest['sub_quality'].isin(['Hot', 'Iconic', 'Incumbent', 'Legacy']) |
        latest['calculated_sub_quality'].notna()
    ].copy()

    has_designation['designation_change'] = (
        has_designation['sub_quality'].fillna('') != has_designation['calculated_sub_quality'].fillna('')
    )

    tab2 = has_designation[[
        'company_id', 'company_name', 'segment', 'mosaic_score',
        'sub_quality', 'calculated_sub_quality', 'designation_change',
        'production_qot', 'calculated_qot',
        'last_rule_applied'
    ]].copy()
    tab2 = tab2.rename(columns={
        'sub_quality': 'current_sub_quality',
        'calculated_sub_quality': 'model_sub_quality',
    })
    tab2 = tab2.sort_values(['designation_change', 'model_sub_quality', 'calculated_qot'],
                            ascending=[False, True, False])
    tab2_path = os.path.join(output_dir, 'Tab 2 - Sub-Quality Designations.csv')
    tab2.to_csv(tab2_path, index=False)

    # Summary stats
    changes = tab2['designation_change'].sum()
    model_counts = tab2['model_sub_quality'].value_counts()
    print(f"  Tab 2: {len(tab2)} companies with designations -> {tab2_path}")
    print(f"    Designation changes: {changes}")
    for sq in ['Hot', 'Iconic', 'Incumbent', 'Legacy']:
        print(f"    Model {sq}: {model_counts.get(sq, 0)}")

    # --- Tab 4: Sub-Quality Transitions ---
    # Show every company where sub_quality designation changed, grouped by transition
    transitions = latest.copy()
    transitions['current_sq'] = transitions['sub_quality'].fillna('None')
    transitions['model_sq'] = transitions['calculated_sub_quality'].fillna('None')
    transitions = transitions[transitions['current_sq'] != transitions['model_sq']]

    # Define transition categories for sorting
    transition_order = {
        # Newly designated as Hot (promoted)
        'None → Hot': 0,
        'Iconic → Hot': 1,
        'Incumbent → Hot': 2,
        # Newly Iconic
        'None → Iconic': 3,
        'Hot → Iconic': 4,
        'Incumbent → Iconic': 5,
        # Demoted from Hot
        'Hot → Incumbent': 6,
        'Hot → Legacy': 7,
        # Iconic demotions
        'Iconic → Incumbent': 8,
        'Iconic → Legacy': 9,
        # Incumbent demotions
        'Incumbent → Legacy': 10,
        # Legacy upgrades
        'Legacy → Incumbent': 11,
        'Legacy → Iconic': 12,
        'Legacy → Hot': 13,
    }

    transitions['transition'] = transitions['current_sq'] + ' → ' + transitions['model_sq']
    transitions['sort_key'] = transitions['transition'].map(transition_order).fillna(99)
    transitions = transitions.sort_values(['sort_key', 'company_name'])

    tab4 = transitions[[
        'company_id', 'company_name', 'segment', 'mosaic_score',
        'transition', 'current_sq', 'model_sq',
        'production_qot', 'calculated_qot', 'last_rule_applied'
    ]].copy()
    tab4 = tab4.rename(columns={
        'current_sq': 'current_sub_quality',
        'model_sq': 'model_sub_quality',
    })
    tab4_path = os.path.join(output_dir, 'Tab 4 - Sub-Quality Transitions.csv')
    tab4.to_csv(tab4_path, index=False)

    # Summary by transition type
    print(f"  Tab 4: {len(tab4)} sub-quality transitions -> {tab4_path}")
    transition_counts = tab4['transition'].value_counts()
    for t in sorted(transition_counts.index, key=lambda x: transition_order.get(x, 99)):
        print(f"    {t}: {transition_counts[t]}")

    # --- Tab 3: All Other Quality Changes ---
    other_changes = latest[
        (latest['delta'] != 0) &
        ~latest['company_id'].isin(q5_company_ids)
    ].copy()
    other_changes = other_changes.sort_values('delta', key=abs, ascending=False)

    tab3 = other_changes[[
        'company_id', 'company_name', 'segment', 'mosaic_score',
        'sub_quality', 'production_qot', 'calculated_qot', 'delta',
        'direction', 'last_rule_applied'
    ]].copy()
    tab3_path = os.path.join(output_dir, 'Tab 3 - All Other Quality Changes.csv')
    tab3.to_csv(tab3_path, index=False)
    print(f"  Tab 3: {len(tab3)} other quality changes -> {tab3_path}")

    return tab1, tab2, tab3, tab4


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate spec-aligned QOT test output')
    parser.add_argument('--output-dir', default='./output', help='Output directory for CSVs')
    parser.add_argument('--publish', action='store_true', help='Also publish scores to DB')
    parser.add_argument('--name', default='Spec Aligned v1', help='Config name for DB publish')
    args = parser.parse_args()

    print("QOT Spec-Aligned Test Output Generator")
    print("=" * 50)

    # Connect to DB
    conn = get_connection()
    print("Connected to database")

    # Load data
    df = load_temporal_metrics()
    print(f"Loaded {len(df):,} company-year records")

    # Run scoring
    print("Running spec-aligned scoring...")
    scored, config = run_spec_scoring(df, conn)
    print(f"Scoring complete. Quality distribution:")
    for q in range(1, 6):
        count = (scored['calculated_qot'] == q).sum()
        print(f"  Q{q}: {count:,}")

    # Generate test outputs
    print("\nGenerating test output CSVs...")
    tab1, tab2, tab3, tab4 = generate_outputs(scored, conn, args.output_dir)

    # Summary
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Q5 changes: {len(tab1)} companies")
    print(f"  Sub-quality designations: {len(tab2)} companies")
    print(f"  Sub-quality transitions: {len(tab4)} companies")
    print(f"  Other quality changes: {len(tab3)} companies")

    # Optionally publish to DB
    if args.publish:
        print("\nPublishing to database...")
        config_hash, count = write_calculated_qot(scored, config, conn)
        save_config(config, conn, name=args.name)
        print(f"  Wrote {count:,} records (hash: {config_hash})")

    # Export config for reference
    config_path = os.path.join(args.output_dir, 'spec_aligned_config.json')
    # Remove runtime keys before export
    export_cfg = {k: v for k, v in config.items() if not k.startswith('_')}
    with open(config_path, 'w') as f:
        json.dump(export_cfg, f, indent=2, default=str)
    print(f"\nConfig exported to {config_path}")

    conn.close()
    print("Done!")


if __name__ == '__main__':
    main()
