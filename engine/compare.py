"""
Comparison engine: match calculated QOT against production DB.
Compares against both the qot table and companies table.
"""
import pandas as pd
import numpy as np
from utils.caching import load_production_qot, load_production_companies
from utils.config import QUALITY_STRING_TO_INT

BASELINE_MATCH_RATE = 82.25


def compare_against_qot_table(calculated_df: pd.DataFrame, conn) -> dict:
    """Compare calculated_qot against production qot table.
    Returns dict with match rates, breakdowns, and mismatches.
    """
    prod = load_production_qot(conn)
    prod = prod.rename(columns={'qot': 'db_qot'})
    prod['year'] = prod['year'].astype(int)
    prod['db_qot'] = prod['db_qot'].astype(int)

    # Join
    calc_cols = ['company_id', 'year', 'calculated_qot', 'segment', 'company_name', 'rules_applied', 'last_rule_applied']
    available_cols = [c for c in calc_cols if c in calculated_df.columns]
    merged = calculated_df[available_cols].merge(prod, on=['company_id', 'year'], how='inner')

    if len(merged) == 0:
        return {
            "overall_match_rate": 0.0,
            "by_segment": {},
            "by_quality": {},
            "by_year": {},
            "delta_from_baseline": -BASELINE_MATCH_RATE,
            "mismatches": pd.DataFrame(),
            "total_compared": 0,
        }

    matched = merged['calculated_qot'] == merged['db_qot']
    overall = matched.mean() * 100

    # By segment
    by_segment = {}
    if 'segment' in merged.columns:
        for seg, group in merged.groupby('segment'):
            by_segment[seg] = (group['calculated_qot'] == group['db_qot']).mean() * 100

    # By quality level
    by_quality = {}
    for q in range(1, 6):
        subset = merged[merged['db_qot'] == q]
        if len(subset) > 0:
            by_quality[q] = (subset['calculated_qot'] == subset['db_qot']).mean() * 100

    # By year
    by_year = {}
    for yr, group in merged.groupby('year'):
        by_year[int(yr)] = (group['calculated_qot'] == group['db_qot']).mean() * 100

    # Mismatches
    mismatches = merged[~matched].copy()
    mismatches['direction'] = np.where(
        mismatches['calculated_qot'] > mismatches['db_qot'], 'upgraded', 'downgraded'
    )
    mismatches['diff'] = mismatches['calculated_qot'] - mismatches['db_qot']

    # Full comparison data with diff column
    full_comparison = merged.copy()
    full_comparison['diff'] = full_comparison['calculated_qot'] - full_comparison['db_qot']
    full_comparison['direction'] = np.where(
        full_comparison['diff'] > 0, 'upgraded',
        np.where(full_comparison['diff'] < 0, 'downgraded', 'match')
    )

    return {
        "overall_match_rate": round(overall, 2),
        "by_segment": by_segment,
        "by_quality": by_quality,
        "by_year": by_year,
        "delta_from_baseline": round(overall - BASELINE_MATCH_RATE, 2),
        "mismatches": mismatches,
        "full_comparison": full_comparison,
        "total_compared": len(merged),
    }


def compare_against_companies_table(calculated_df: pd.DataFrame, conn) -> dict:
    """Compare most recent year per company against companies.quality and sub_quality.

    companies.quality: 'Low', 'Medium', 'High', 'Top'
    companies.sub_quality: null, 'Hot', 'Iconic', 'Legacy'
    Iconic = companies that achieved Q5/Hot at some point historically.
    """
    prod = load_production_companies(conn)

    # Get most recent year per company from calculated data
    latest = calculated_df.sort_values('year').groupby('company_id').last().reset_index()

    # Drop overlapping columns from calculated data before merging
    drop_cols = [c for c in ['quality', 'sub_quality'] if c in latest.columns]
    if drop_cols:
        latest = latest.drop(columns=drop_cols)

    merged = latest.merge(prod, on='company_id', how='inner')

    if len(merged) == 0:
        return {
            "quality_match_rate": 0.0,
            "sub_quality_breakdown": {},
            "total_compared": 0,
        }

    # Map companies.quality string to numeric
    merged['db_quality_int'] = merged['quality'].map(QUALITY_STRING_TO_INT)

    # For "Top" quality, both Q4 and Q5 are acceptable matches
    quality_match = (
        (merged['calculated_qot'] == merged['db_quality_int']) |
        ((merged['quality'] == 'Top') & (merged['calculated_qot'] >= 4))
    )
    quality_match_rate = quality_match.mean() * 100

    # Sub-quality analysis
    sub_quality_breakdown = {}
    for sq in ['Hot', 'Iconic', 'Legacy']:
        subset = merged[merged['sub_quality'] == sq]
        if len(subset) > 0:
            if sq == 'Hot':
                # Hot should map to Q5
                match_rate = (subset['calculated_qot'] == 5).mean() * 100
            elif sq == 'Iconic':
                # Iconic = historically achieved Q5; check if any year was Q5
                iconic_ids = subset['company_id'].unique()
                ever_q5 = calculated_df[
                    (calculated_df['company_id'].isin(iconic_ids)) &
                    (calculated_df['calculated_qot'] == 5)
                ]['company_id'].unique()
                match_rate = len(set(ever_q5) & set(iconic_ids)) / len(iconic_ids) * 100
            else:
                # Legacy: should NOT be Q5
                match_rate = (subset['calculated_qot'] < 5).mean() * 100

            sub_quality_breakdown[sq] = {
                "match_rate": round(match_rate, 2),
                "count": len(subset),
            }

    return {
        "quality_match_rate": round(quality_match_rate, 2),
        "sub_quality_breakdown": sub_quality_breakdown,
        "total_compared": len(merged),
    }


def compute_all_comparisons(calculated_df: pd.DataFrame, conn) -> dict:
    """Run both comparisons and return unified results."""
    qot_result = compare_against_qot_table(calculated_df, conn)
    comp_result = compare_against_companies_table(calculated_df, conn)

    # Enrich full_comparison with companies table quality/sub_quality
    full_comp = qot_result.get('full_comparison')
    if full_comp is not None and len(full_comp) > 0:
        companies = load_production_companies(conn)
        companies = companies.rename(columns={
            'quality': 'companies_quality',
            'sub_quality': 'companies_sub_quality',
        })
        # Drop if already present to avoid collision
        drop_cols = [c for c in ['companies_quality', 'companies_sub_quality'] if c in full_comp.columns]
        if drop_cols:
            full_comp = full_comp.drop(columns=drop_cols)
        full_comp = full_comp.merge(companies, on='company_id', how='left')
        qot_result['full_comparison'] = full_comp

    return {
        "qot_table": qot_result,
        "companies_table": comp_result,
        "calculated_df": calculated_df,
    }
