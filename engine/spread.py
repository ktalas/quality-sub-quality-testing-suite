"""
Spread quality logic: temporal spreading with progress multipliers.
Ported from qot_calculator/spread_quality.py with vectorized implementation.
Uses fixed defaults (V2 will make these configurable).
"""
import numpy as np
import pandas as pd

# Valuation milestones (in millions) -> progress multiplier
VALUATION_MILESTONES = [
    (10_000, 1.0),   # Decacorn
    (1_000, 0.8),    # Unicorn
    (500, 0.7),
    (100, 0.5),
    (10, 0.3),
]

# Revenue milestones (in dollars) -> progress multiplier
REVENUE_MILESTONES = [
    (1_000_000_000, 1.0),
    (500_000_000, 0.9),
    (200_000_000, 0.8),
    (100_000_000, 0.7),
    (50_000_000, 0.6),
    (30_000_000, 0.5),
    (10_000_000, 0.4),
]

# Exit value thresholds (in millions) -> quality boost
EXIT_BOOSTS = [
    (10_000, 5.0),
    (5_000, 4.5),
    (1_000, 4.0),
    (500, 3.5),
]

# Post-exit maintenance multipliers by exit value (millions)
POST_EXIT_MAINT = [
    (1_000, 0.95),
    (500, 0.90),
    (0, 0.80),
]


def apply_spread_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Apply temporal spreading with progress multipliers and exit handling.
    Modifies calculated_qot based on how far along the company was at each year.
    """
    df = df.copy()

    # Use peak_valuation_to_date if available, else eoy_valuation
    peak_val = df.get('peak_valuation_to_date', df['eoy_valuation']).fillna(0)
    revenue = df['revenue'].fillna(0)
    has_deal = df['deals_count'].fillna(0) > 0

    # Calculate valuation-based progress multiplier
    val_mult = pd.Series(0.2, index=df.index)
    for threshold, mult in VALUATION_MILESTONES:
        val_mult = np.where(peak_val >= threshold, np.maximum(val_mult, mult), val_mult)

    # Calculate revenue-based progress multiplier
    rev_mult = pd.Series(0.2, index=df.index)
    for threshold, mult in REVENUE_MILESTONES:
        rev_mult = np.where(revenue >= threshold, np.maximum(rev_mult, mult), rev_mult)

    # For public companies, revenue weighs equally; for others, 80%
    is_public = df['segment'] == 'Public'
    progress = np.where(is_public, np.maximum(val_mult, rev_mult),
                        np.maximum(val_mult, rev_mult * 0.8))

    # Activity bonus
    progress = np.where(has_deal, np.minimum(1.0, progress + 0.1), progress)

    # Apply progress multiplier to calculated_qot
    base_qot = df['calculated_qot'].astype(float)
    spread_score = base_qot * progress

    # Exit year handling
    exit_val = df.get('exit_value', pd.Series(np.nan, index=df.index)).fillna(0)
    years_since = df.get('years_since_exit', pd.Series(np.nan, index=df.index))
    is_exit_year = years_since.fillna(-1) == 0

    for threshold, boost in EXIT_BOOSTS:
        mask = is_exit_year & (exit_val >= threshold)
        spread_score = np.where(mask, np.maximum(spread_score, boost), spread_score)

    # Post-exit maintenance
    is_post_exit = (years_since.fillna(-1) > 0)
    for threshold, maint in POST_EXIT_MAINT:
        mask = is_post_exit & (exit_val >= threshold)
        spread_score = np.where(mask, np.maximum(spread_score, base_qot * maint), spread_score)

    # Minimum for established companies
    company_age = df.get('company_age', pd.Series(np.nan, index=df.index))
    established = (company_age.fillna(0) > 5) & (spread_score < 1)
    spread_score = np.where(established, 1.0, spread_score)

    # Round to integer QOT 1-5
    df['calculated_qot'] = np.round(spread_score).clip(1, 5).astype(int)

    return df
