"""
All QOT scoring rules as isolated, vectorized functions.
Each rule: apply_X(df, params) -> df with 'calculated_qot' updated.
"""
import numpy as np
import pandas as pd


def _tag(df, mask, rule_name):
    """Tag records modified by a rule."""
    if mask.any():
        df.loc[mask, 'last_rule_applied'] = rule_name
        for idx in df.index[mask]:
            df.at[idx, 'rules_applied'] = df.at[idx, 'rules_applied'] + [rule_name]
    return df


# ── Phase 1: Base Assignment ──────────────────────────────────────────────

def apply_baseline(df, params):
    """Dispatch to the selected baseline strategy."""
    strategy = params.get('baseline_strategy', 'quality_table')
    if strategy == 'mosaic_only':
        return apply_base_mosaic_only(df, params)
    elif strategy == 'qot_table':
        return apply_base_qot_table(df, params)
    elif strategy == 'blank_slate':
        return apply_base_blank_slate(df, params)
    else:
        return apply_base_quality_stretch(df, params)


def apply_base_quality_stretch(df, params):
    """Stretch current quality_score across all years (baseline approach)."""
    df['calculated_qot'] = df['quality_score'].fillna(1).astype(int).clip(1, 5)
    return df


def apply_base_mosaic_only(df, params):
    """Derive baseline quality purely from mosaic_score thresholds."""
    mosaic = df['mosaic_score'].fillna(0)
    qot = pd.Series(1, index=df.index)

    # Apply thresholds in ascending order (lowest first, highest overwrites)
    t650 = params.get('mosaic_650_threshold', 650)
    t750 = params.get('mosaic_750_threshold', 750)
    t900 = params.get('mosaic_900_threshold', 900)
    f650 = params.get('mosaic_650_floor', 2)
    f750 = params.get('mosaic_750_floor', 3)
    f900 = params.get('mosaic_900_floor', 4)

    qot = qot.where(mosaic < t650, f650)
    qot = qot.where(mosaic < t750, f750)
    qot = qot.where(mosaic < t900, f900)

    df['calculated_qot'] = qot.astype(int).clip(1, 5)
    return df


def apply_base_qot_table(df, params):
    """Use production QOT table values as the baseline."""
    production_qot = params.get('_production_qot_df')
    if production_qot is None:
        return apply_base_quality_stretch(df, params)

    prod = production_qot[['company_id', 'year', 'qot']].copy()
    prod['year'] = prod['year'].astype(int)
    prod['qot'] = prod['qot'].astype(int)

    # Guard against existing 'qot' column
    if 'qot' in df.columns:
        df = df.drop(columns=['qot'])

    df = df.merge(prod, on=['company_id', 'year'], how='left')

    # Use production qot where available, fall back to quality_score
    df['calculated_qot'] = df['qot'].fillna(
        df['quality_score'].fillna(1).astype(int)
    ).astype(int).clip(1, 5)
    df = df.drop(columns=['qot'], errors='ignore')
    return df


def apply_base_blank_slate(df, params):
    """All companies start at Q1. Quality is built entirely by subsequent rules."""
    df['calculated_qot'] = 1
    return df


def apply_sub_quality_upgrades(df, params):
    """Hot/Iconic sub_quality -> Q5."""
    if params.get("upgrade_hot_to_5", True):
        mask = df['sub_quality'] == 'Hot'
        df.loc[mask, 'calculated_qot'] = 5
        df = _tag(df, mask, 'sub_quality_hot')

    if params.get("upgrade_iconic_to_5", True):
        mask = df['sub_quality'] == 'Iconic'
        df.loc[mask, 'calculated_qot'] = 5
        df = _tag(df, mask, 'sub_quality_iconic')

    return df


def apply_mosaic_upgrades(df, params):
    """Mosaic score floor system."""
    tiers = [
        ('mosaic_900_threshold', 'mosaic_900_floor'),
        ('mosaic_750_threshold', 'mosaic_750_floor'),
        ('mosaic_650_threshold', 'mosaic_650_floor'),
    ]
    for thresh_key, floor_key in tiers:
        thresh = params.get(thresh_key, 900)
        floor = params.get(floor_key, 4)
        mask = (df['mosaic_score'].fillna(0) >= thresh) & (df['calculated_qot'] < floor)
        df.loc[mask, 'calculated_qot'] = floor
        df = _tag(df, mask, f'mosaic_{int(thresh)}')

    return df


# ── Phase 2: Standard Upgrades ────────────────────────────────────────────

# Revenue bucket definitions: (key_suffix, lower_bound, upper_bound)
REVENUE_BUCKETS = [
    ("0_10m", 0, 10_000_000),
    ("10m_30m", 10_000_000, 30_000_000),
    ("30m_50m", 30_000_000, 50_000_000),
    ("50m_200m", 50_000_000, 200_000_000),
    ("200m_500m", 200_000_000, 500_000_000),
    ("500m_1b", 500_000_000, 1_000_000_000),
    ("1b_3b", 1_000_000_000, 3_000_000_000),
    ("3b_10b", 3_000_000_000, 10_000_000_000),
    ("10b_plus", 10_000_000_000, float('inf')),
]


def apply_revenue_upgrades(df, params):
    """Tiered revenue-based upgrades: +1 quality per bucket if growth threshold met."""
    if not params.get("enable_revenue_upgrade", False):
        return df

    public_only = params.get('rev_upgrade_public_only', False)

    for suffix, lower, upper in REVENUE_BUCKETS:
        bucket_cfg = params.get(f'rev_bucket_{suffix}', {})
        if not bucket_cfg.get('enabled', False):
            continue

        growth_period = bucket_cfg.get('growth_period', '3y')
        growth_threshold = bucket_cfg.get('growth_threshold', 0.30)

        growth_col = 'rev_growth_1y' if growth_period == '1y' else 'rev_growth_3y'

        in_bucket = (df['revenue'] >= lower)
        if upper != float('inf'):
            in_bucket = in_bucket & (df['revenue'] < upper)

        mask = (
            in_bucket &
            (df[growth_col] >= growth_threshold) &
            (df['calculated_qot'] < 5)
        )

        if public_only:
            mask = mask & (df['segment'] == 'Public')

        df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] + 1).clip(upper=5)
        df = _tag(df, mask, f'revenue_upgrade_{suffix}')

    return df


def apply_public_revenue_upgrades(df, params):
    """Public company revenue upgrades: $5B+ revenue + growth."""
    if not params.get("public_rev_upgrade_enabled", False):
        return df
    mask = (
        (df['segment'] == 'Public') &
        (df['revenue'] >= params['public_rev_upgrade_min_revenue']) &
        (df['rev_growth_3y'] >= params['public_rev_upgrade_growth_threshold']) &
        (df['calculated_qot'] < params.get('rev_upgrade_target_quality', 5))
    )
    df.loc[mask, 'calculated_qot'] = params.get('rev_upgrade_target_quality', 5)
    return _tag(df, mask, 'public_revenue_upgrade')


def apply_valuation_upgrades(df, params):
    """Unicorn/Decacorn floor + valuation growth upgrades."""
    if params.get("enable_unicorn_upgrade", False):
        floor = params['unicorn_upgrade_quality_floor']
        mask = df['is_unicorn'] & (df['calculated_qot'] < floor)
        df.loc[mask, 'calculated_qot'] = floor
        df = _tag(df, mask, 'unicorn_floor')

    if params.get("enable_decacorn_upgrade", False):
        floor = params['decacorn_upgrade_quality_floor']
        mask = df['is_decacorn'] & (df['calculated_qot'] < floor)
        df.loc[mask, 'calculated_qot'] = floor
        df = _tag(df, mask, 'decacorn_floor')

    if params.get("enable_val_growth_upgrade", False):
        mask = df['val_growth_3y'] >= params['val_growth_threshold']
        if params.get("require_revenue_validation", False):
            mask = mask & (df['revenue'] >= params['val_upgrade_min_revenue'])
        target = params['val_growth_upgrade_target']
        upgrade_mask = mask & (df['calculated_qot'] < target)
        df.loc[upgrade_mask, 'calculated_qot'] = target
        df = _tag(df, upgrade_mask, 'val_growth_upgrade')

    return df


def apply_tier1_vc_upgrades(df, params):
    """Add +1 quality for companies with Tier 1 VC involvement at enabled funding stages.

    Uses the configurable VC list (params['tier1_vc_list']) if provided,
    otherwise falls back to has_tier1_vc flag from the data pipeline.
    """
    if not params.get("enable_tier1_vc_upgrade", False):
        return df
    if 'funding_rounds' not in df.columns:
        return df

    from utils.config import FUNDING_STAGES, DEFAULT_TIER_1_VCS

    # Determine T1 VC presence: custom list or pre-computed flag
    custom_list = params.get('tier1_vc_list')
    if custom_list is not None and '_investor_data' in params:
        # Recompute has_tier1_vc using custom list
        inv_df = params['_investor_data']
        tier1_set = set(custom_list)
        tier1_companies = inv_df[inv_df['investor_name'].isin(tier1_set)].groupby(
            ['company_id', 'year']
        ).size().reset_index(name='_t1_count')
        tier1_pairs = set(zip(tier1_companies['company_id'], tier1_companies['year']))
        is_tier1 = pd.Series(
            [((cid, yr) in tier1_pairs) for cid, yr in zip(df['company_id'], df['year'])],
            index=df.index,
        )
    elif 'has_tier1_vc' in df.columns:
        is_tier1 = df['has_tier1_vc'] == True
    else:
        return df

    # Map config keys to stage names
    stage_config_map = {
        "tier1_vc_stage_seed": "Seed",
        "tier1_vc_stage_series_a": "Series A",
        "tier1_vc_stage_series_b": "Series B",
        "tier1_vc_stage_series_c": "Series C",
        "tier1_vc_stage_series_d": "Series D",
        "tier1_vc_stage_late": "Late Stage",
        "tier1_vc_stage_growth_equity": "Growth Equity",
        "tier1_vc_stage_pe": "PE",
    }

    # Collect all round names for enabled stages
    enabled_rounds = set()
    for config_key, stage_name in stage_config_map.items():
        if params.get(config_key, False):
            enabled_rounds.update(FUNDING_STAGES[stage_name])

    if not enabled_rounds:
        return df

    # Check if any enabled round appears in the company-year's funding_rounds string
    def has_enabled_round(funding_str):
        if not funding_str or pd.isna(funding_str):
            return False
        rounds = [r.strip() for r in str(funding_str).split(',')]
        return bool(set(rounds) & enabled_rounds)

    has_stage = df['funding_rounds'].apply(has_enabled_round)
    mask = is_tier1 & has_stage & (df['calculated_qot'] < 5)
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] + 1).clip(upper=5)
    return _tag(df, mask, 'tier1_vc_upgrade')


# ── Phase 3: Advanced Rules ───────────────────────────────────────────────

def apply_exceptional_val_growth(df, params):
    """200%+ 3yr valuation growth -> Q5, non-PE only."""
    if not params.get("enable_exceptional_val_growth", True):
        return df
    mask = (
        (df['segment'] != 'PE') &
        (df['val_growth_3y'] >= params['exceptional_val_growth_threshold']) &
        (df['calculated_qot'] < 5)
    )
    df.loc[mask, 'calculated_qot'] = 5
    return _tag(df, mask, 'exceptional_val_growth')


def apply_pe_hot_rules(df, params):
    """PE-specific Q5 rules: very high revenue + growth."""
    if not params.get("enable_pe_hot_rules", True):
        return df
    # High-rev PE: $50B+ revenue + 50%+ growth
    mask_high = (
        (df['segment'] == 'PE') &
        (df['revenue'] >= params['pe_hot_rev_threshold_high']) &
        (df['rev_growth_3y'] >= params['pe_hot_growth_threshold_high']) &
        (df['calculated_qot'] < 5)
    )
    # Lower-rev PE: $20B+ revenue + 75%+ growth
    mask_low = (
        (df['segment'] == 'PE') &
        (df['revenue'] >= params['pe_hot_rev_threshold_low']) &
        (df['rev_growth_3y'] >= params['pe_hot_growth_threshold_low']) &
        (df['calculated_qot'] < 5)
    )
    combined = mask_high | mask_low
    df.loc[combined, 'calculated_qot'] = 5
    return _tag(df, combined, 'pe_hot_rules')


def apply_rev_growth_upgrade(df, params):
    """Exceptional revenue growth: $100M+ rev + 150%+ growth -> Q5."""
    if not params.get("enable_rev_growth_upgrade", True):
        return df
    mask = (
        (df['revenue'] >= params['rev_growth_upgrade_min_revenue']) &
        (df['rev_growth_3y'] >= params['rev_growth_upgrade_threshold']) &
        (df['calculated_qot'] < 5)
    )
    df.loc[mask, 'calculated_qot'] = 5
    return _tag(df, mask, 'rev_growth_upgrade')


def apply_stagnant_val_rev_check(df, params):
    """Stagnant valuations ($1B+, <10% growth) require exceptional revenue growth for Q5.
    Downgrades Q5 companies that don't meet tiered revenue growth requirements.
    """
    if not params.get("enable_stagnant_val_rev_check", True):
        return df

    stagnant_q5 = (
        (df['eoy_valuation'] >= 1000) &  # $1B+ valuation (millions)
        (df['val_growth_3y'] <= params.get('stagnant_val_threshold', 0.10)) &
        (df['calculated_qot'] == 5)
    )

    if not stagnant_q5.any():
        return df

    rev_millions = df['revenue'] / 1_000_000

    # Tiered revenue growth requirements
    # Sub-$100M rev: 200%+ growth
    insufficient = stagnant_q5 & (
        ((rev_millions < 100) & (df['rev_growth_3y'] <= 2.0)) |
        ((rev_millions >= 100) & (rev_millions < 300) & (df['rev_growth_3y'] <= 1.0)) |
        ((rev_millions >= 300) & (rev_millions < 1000) & (df['rev_growth_3y'] <= 0.6)) |
        ((rev_millions >= 1000) & (df['rev_growth_3y'] <= 0.4)) |
        (df['revenue'] <= 0)  # no revenue data = insufficient
    )
    df.loc[insufficient, 'calculated_qot'] = 4
    return _tag(df, insufficient, 'stagnant_val_rev_check')


def apply_no_recent_funding_check(df, params):
    """Higher revenue bar for companies with no deals since cutoff year.
    Downgrades Q5 companies that haven't raised recently and lack revenue growth.
    """
    if not params.get("enable_no_recent_funding_check", True):
        return df

    cutoff_year = params.get('no_recent_funding_cutoff_year', 2022)
    from datetime import datetime
    current_year = datetime.now().year
    min_years = current_year - cutoff_year

    no_recent_q5 = (
        (df['eoy_valuation'] >= 1000) &
        (df['years_since_last_deal'] >= min_years) &
        (df['calculated_qot'] == 5)
    )

    if not no_recent_q5.any():
        return df

    rev_millions = df['revenue'] / 1_000_000

    # Even higher thresholds than stagnant_val check
    insufficient = no_recent_q5 & (
        ((rev_millions < 100) & (df['rev_growth_3y'] <= 3.0)) |
        ((rev_millions >= 100) & (rev_millions < 300) & (df['rev_growth_3y'] <= 1.5)) |
        ((rev_millions >= 300) & (rev_millions < 1000) & (df['rev_growth_3y'] <= 1.0)) |
        ((rev_millions >= 1000) & (df['rev_growth_3y'] <= 0.7)) |
        (df['revenue'] <= 0)
    )
    df.loc[insufficient, 'calculated_qot'] = 4
    return _tag(df, insufficient, 'no_recent_funding_check')


# ── Phase 4: Exclusions and Downgrades ────────────────────────────────────

def apply_legacy_exclusion(df, params):
    """Legacy companies cannot be Q5."""
    if not params.get("enable_legacy_exclusion", True):
        return df
    mask = (df['sub_quality'] == 'Legacy') & (df['calculated_qot'] == 5)
    df.loc[mask, 'calculated_qot'] = 4
    return _tag(df, mask, 'legacy_exclusion')


def apply_legacy_penalty(df, params):
    """Cap quality for legacy companies."""
    if not params.get("enable_legacy_penalty", False):
        return df
    cap = params.get('legacy_penalty_max_quality', 3)
    mask = (df['sub_quality'] == 'Legacy') & (df['calculated_qot'] > cap)
    df.loc[mask, 'calculated_qot'] = cap
    return _tag(df, mask, 'legacy_penalty')


def apply_revenue_decline_downgrade(df, params):
    """Downgrade on revenue decline for specified segments."""
    if not params.get("enable_revenue_decline_downgrade", False):
        return df
    segments = params.get('rev_decline_segments', ['Public'])
    mask = (
        (df['rev_growth_3y'] <= params['rev_decline_threshold']) &
        (df['segment'].isin(segments)) &
        (df['calculated_qot'] > 1)
    )
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - 1).clip(lower=1)
    return _tag(df, mask, 'revenue_decline_downgrade')


def apply_stagnation_downgrade(df, params):
    """Multi-year stagnation downgrade (revenue or valuation)."""
    if not params.get("enable_stagnation_downgrade", False):
        return df
    rev_thresh = params.get('rev_stagnation_years_threshold', 5)
    val_thresh = params.get('val_stagnation_years_threshold', 5)
    amount = params.get('stagnation_downgrade_amount', 1)

    mask = (
        ((df['rev_stagnation_years'] >= rev_thresh) | (df['val_stagnation_years'] >= val_thresh)) &
        (df['calculated_qot'] > 1)
    )
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - amount).clip(lower=1)
    return _tag(df, mask, 'stagnation_downgrade')


def apply_val_decline_downgrade(df, params):
    """VC valuation decline downgrade."""
    if not params.get("enable_val_decline_downgrade", True):
        return df
    mask = (
        (df['segment'] == 'VC') &
        (df['val_growth_3y'] <= params['val_decline_threshold']) &
        (df['calculated_qot'] > 1)
    )
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - 1).clip(lower=1)
    return _tag(df, mask, 'val_decline_downgrade')


def apply_growth_rev_stagnation(df, params):
    """Growth segment: revenue stagnation 3+ years."""
    if not params.get("enable_growth_rev_stagnation", True):
        return df
    years = params.get('growth_rev_stagnation_years', 3)
    mask = (
        (df['segment'] == 'Growth') &
        (df['rev_stagnation_years'] >= years) &
        (df['calculated_qot'] > 1)
    )
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - 1).clip(lower=1)
    return _tag(df, mask, 'growth_rev_stagnation')


# ── Phase 5: Segment & Acquisition ────────────────────────────────────────

def apply_segment_transition_rules(df, params):
    """Public -> PE downgrade and taken-private cap."""
    if params.get("enable_public_to_pe_downgrade", True):
        mask = (
            (df['prev_segment'] == 'Public') &
            (df['segment'] == 'PE') &
            (df['segment_changed'] == True) &
            (df['calculated_qot'] >= params['public_to_pe_min_quality'])
        )
        amount = params.get('public_to_pe_downgrade_amount', 1)
        df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - amount).clip(lower=1)
        df = _tag(df, mask, 'public_to_pe_downgrade')

    if params.get("enable_taken_private_cap", False):
        mask = (
            (df['prev_segment'] == 'Public') &
            (df['segment'] == 'PE') &
            (df['calculated_qot'] > 3)
        )
        df.loc[mask, 'calculated_qot'] = 3
        df = _tag(df, mask, 'taken_private_cap')

    return df


def apply_pe_deal_decline(df, params):
    """PE companies with declining deal activity."""
    if not params.get("enable_pe_deal_decline_downgrade", False):
        return df
    mask = (
        (df['segment'] == 'PE') &
        (df['deal_trend_3y'] <= params['pe_deal_decline_threshold']) &
        (df['calculated_qot'] > 1)
    )
    df.loc[mask, 'calculated_qot'] = (df.loc[mask, 'calculated_qot'] - 1).clip(lower=1)
    return _tag(df, mask, 'pe_deal_decline')


def apply_rev_declining_exclusion(df, params):
    """Companies with any negative 3yr revenue growth cannot be Q5."""
    if not params.get("enable_rev_declining_exclusion", False):
        return df
    mask = (
        (df['rev_growth_3y'] < 0) &
        (df['rev_growth_3y'].notna()) &
        (df['calculated_qot'] == 5)
    )
    df.loc[mask, 'calculated_qot'] = 4
    return _tag(df, mask, 'rev_declining_exclusion')


def apply_decacorn_revenue_validation(df, params):
    """Decacorns need revenue validation to be Q5.
    PE decacorns: need strong revenue growth.
    Non-PE decacorns: need valuation growth + revenue, or revenue growth + revenue.
    """
    if not params.get("enable_decacorn_revenue_validation", False):
        return df

    pe_rev_growth = params.get('decacorn_pe_rev_growth_threshold', 0.75)
    nonpe_val_growth = params.get('decacorn_nonpe_val_growth_threshold', 0.30)
    nonpe_rev_growth = params.get('decacorn_nonpe_rev_growth_threshold', 0.30)
    min_revenue = params.get('decacorn_min_revenue', 500_000_000)

    # PE decacorns: need revenue growth threshold
    pe_decacorn_q5 = (
        (df['is_decacorn']) &
        (df['segment'] == 'PE') &
        (df['calculated_qot'] == 5)
    )
    pe_fail = pe_decacorn_q5 & (
        (df['rev_growth_3y'] < pe_rev_growth) | df['rev_growth_3y'].isna()
    )
    df.loc[pe_fail, 'calculated_qot'] = 4
    df = _tag(df, pe_fail, 'decacorn_rev_validation_pe')

    # Non-PE decacorns: need (val growth + revenue) or (rev growth + revenue)
    nonpe_decacorn_q5 = (
        (df['is_decacorn']) &
        (df['segment'] != 'PE') &
        (df['calculated_qot'] == 5)
    )
    has_val_path = (
        (df['val_growth_3y'] >= nonpe_val_growth) &
        (df['revenue'] >= min_revenue)
    )
    has_rev_path = (
        (df['rev_growth_3y'] >= nonpe_rev_growth) &
        (df['revenue'] >= min_revenue)
    )
    nonpe_fail = nonpe_decacorn_q5 & ~has_val_path & ~has_rev_path
    df.loc[nonpe_fail, 'calculated_qot'] = 4
    return _tag(df, nonpe_fail, 'decacorn_rev_validation_nonpe')


def apply_unicorn_growth_validation(df, params):
    """Unicorns need strong valuation growth + minimum revenue to be Q5."""
    if not params.get("enable_unicorn_growth_validation", False):
        return df

    val_growth = params.get('unicorn_val_growth_threshold', 0.75)
    min_revenue = params.get('unicorn_min_revenue', 100_000_000)

    unicorn_q5 = (
        (df['is_unicorn']) &
        (~df['is_decacorn']) &  # decacorns handled separately
        (df['calculated_qot'] == 5)
    )
    fail = unicorn_q5 & (
        (df['val_growth_3y'] < val_growth) |
        (df['val_growth_3y'].isna()) |
        (df['revenue'] < min_revenue)
    )
    df.loc[fail, 'calculated_qot'] = 4
    return _tag(df, fail, 'unicorn_growth_validation')


def apply_public_low_growth_downgrade(df, params):
    """Public companies with no sub_quality and low revenue growth get downgraded."""
    if not params.get("enable_public_low_growth_downgrade", True):
        return df
    growth_thresh = params.get('public_low_growth_threshold', 0.05)
    min_quality = params.get('public_low_growth_min_quality', 4)
    target = params.get('public_low_growth_target', 3)
    mask = (
        (df['segment'] == 'Public') &
        (df['sub_quality'].isna() | (df['sub_quality'] == '')) &
        (df['rev_growth_3y'] < growth_thresh) &
        (df['rev_growth_3y'].notna()) &
        (df['revenue'] > 0) &
        (df['calculated_qot'] >= min_quality) &
        (df['year'] < df['year'].max())  # exclude most recent incomplete year
    )
    df.loc[mask, 'calculated_qot'] = target
    return _tag(df, mask, 'public_low_growth_downgrade')


def apply_public_large_rev_upgrade(df, params):
    """Public companies with large revenue but Q1 get upgraded to Q2."""
    if not params.get("enable_public_large_rev_upgrade", True):
        return df
    rev_thresh = params.get('public_large_rev_threshold', 1_000_000_000)
    mask = (
        (df['segment'] == 'Public') &
        (df['sub_quality'].isna() | (df['sub_quality'] == '')) &
        (df['revenue'] > rev_thresh) &
        (df['calculated_qot'] == 1)
    )
    df.loc[mask, 'calculated_qot'] = 2
    return _tag(df, mask, 'public_large_rev_upgrade')


def apply_acquisition_degradation(df, params):
    """Q5 acquired companies drop after delay period."""
    if not params.get("enable_acquisition_degradation", True):
        return df
    delay = params.get('acquisition_degradation_delay', 2)
    target = params.get('acquisition_degradation_target', 4)
    exit_types = ['Acquired', 'Acq - P2P', 'Acq - Pending', 'Merger']
    mask = (
        (df['exit_type'].isin(exit_types)) &
        (df['years_since_exit'].fillna(-1) >= delay) &
        (df['calculated_qot'] > target)
    )
    df.loc[mask, 'calculated_qot'] = target
    return _tag(df, mask, 'acquisition_degradation')
