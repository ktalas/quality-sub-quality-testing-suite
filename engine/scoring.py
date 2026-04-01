"""
Scoring pipeline orchestrator: runs rules in order.
"""
import pandas as pd
from engine.rules import (
    apply_baseline,
    apply_sub_quality_upgrades,
    apply_mosaic_upgrades,
    apply_no_mosaic_fallback,
    apply_q5_promotions,
    apply_current_year_override,
    apply_revenue_upgrades,
    apply_public_revenue_upgrades,
    apply_valuation_upgrades,
    apply_tier1_vc_upgrades,
    apply_exceptional_val_growth,
    apply_pe_hot_rules,
    apply_rev_growth_upgrade,
    apply_stagnant_val_rev_check,
    apply_no_recent_funding_check,
    apply_legacy_exclusion,
    apply_legacy_penalty,
    apply_revenue_decline_downgrade,
    apply_stagnation_downgrade,
    apply_val_decline_downgrade,
    apply_growth_rev_stagnation,
    apply_segment_transition_rules,
    apply_pe_deal_decline,
    apply_acquisition_degradation,
    apply_public_low_growth_downgrade,
    apply_public_large_rev_upgrade,
    apply_rev_declining_exclusion,
    apply_decacorn_revenue_validation,
    apply_unicorn_growth_validation,
)

# Legacy pipeline (unchanged, for backwards compatibility)
RULE_PIPELINE = [
    # Phase 1: Base assignment
    ("base_quality", apply_baseline),
    ("sub_quality_upgrade", apply_sub_quality_upgrades),
    ("mosaic_upgrade", apply_mosaic_upgrades),

    # Phase 2: Standard upgrades
    ("revenue_upgrade", apply_revenue_upgrades),
    ("public_revenue_upgrade", apply_public_revenue_upgrades),
    ("valuation_upgrade", apply_valuation_upgrades),
    ("tier1_vc_upgrade", apply_tier1_vc_upgrades),

    # Phase 3: Advanced upgrades
    ("exceptional_val_growth", apply_exceptional_val_growth),
    ("pe_hot_rules", apply_pe_hot_rules),
    ("rev_growth_upgrade", apply_rev_growth_upgrade),
    ("stagnant_val_rev_check", apply_stagnant_val_rev_check),
    ("no_recent_funding_check", apply_no_recent_funding_check),

    # Phase 4: Exclusions and downgrades
    ("rev_declining_exclusion", apply_rev_declining_exclusion),
    ("decacorn_revenue_validation", apply_decacorn_revenue_validation),
    ("unicorn_growth_validation", apply_unicorn_growth_validation),
    ("legacy_exclusion", apply_legacy_exclusion),
    ("legacy_penalty", apply_legacy_penalty),
    ("revenue_decline_downgrade", apply_revenue_decline_downgrade),
    ("stagnation_downgrade", apply_stagnation_downgrade),
    ("val_decline_downgrade", apply_val_decline_downgrade),
    ("growth_rev_stagnation", apply_growth_rev_stagnation),

    # Phase 5: Public company fine-tuning (from baseline)
    ("public_low_growth_downgrade", apply_public_low_growth_downgrade),
    ("public_large_rev_upgrade", apply_public_large_rev_upgrade),

    # Phase 6: Segment and acquisition
    ("segment_transition", apply_segment_transition_rules),
    ("pe_deal_decline", apply_pe_deal_decline),
    ("acquisition_degradation", apply_acquisition_degradation),
]

# Spec-aligned pipeline: matches the written spec flow
SPEC_RULE_PIPELINE = [
    # Phase 1: Base Quality (mosaic-based + no-mosaic fallback)
    ("base_quality", apply_baseline),
    ("no_mosaic_fallback", apply_no_mosaic_fallback),
    ("mosaic_upgrade", apply_mosaic_upgrades),

    # Phase 2: Promote to Q5 (compound conditions per segment)
    ("q5_promotions", apply_q5_promotions),

    # Phase 3: Q5 Validation & Guards
    ("stagnant_val_rev_check", apply_stagnant_val_rev_check),
    ("legacy_exclusion", apply_legacy_exclusion),
    ("rev_declining_exclusion", apply_rev_declining_exclusion),

    # Phase 4: Quality Drops (-1 per segment)
    ("stagnation_downgrade", apply_stagnation_downgrade),
    ("val_decline_downgrade", apply_val_decline_downgrade),
    ("revenue_decline_downgrade", apply_revenue_decline_downgrade),
    ("growth_rev_stagnation", apply_growth_rev_stagnation),
    ("pe_deal_decline", apply_pe_deal_decline),
    ("segment_transition", apply_segment_transition_rules),

    # Phase 5: Acquisition Degradation
    ("acquisition_degradation", apply_acquisition_degradation),

    # Phase 6: Current Year Manual Override (last — preserves analyst overrides)
    ("current_year_override", apply_current_year_override),
]


def run_scoring(df: pd.DataFrame, config: dict, production_qot: pd.DataFrame = None) -> pd.DataFrame:
    """Execute all enabled rules in pipeline order."""
    df = df.copy()
    df['rules_applied'] = [[] for _ in range(len(df))]
    df['last_rule_applied'] = ''

    # Inject runtime data into a copy of config (never mutates the original)
    runtime_config = config.copy()
    if production_qot is not None:
        runtime_config['_production_qot_df'] = production_qot

    # Select pipeline based on config
    pipeline = SPEC_RULE_PIPELINE if runtime_config.get('use_spec_pipeline', False) else RULE_PIPELINE

    for rule_name, rule_fn in pipeline:
        # Base rules are always on; others check their enable flag
        enable_key = f"enable_{rule_name}"
        if enable_key in runtime_config and not runtime_config[enable_key]:
            continue
        df = rule_fn(df, runtime_config)

    # Ensure final qot is integer 1-5
    df['calculated_qot'] = df['calculated_qot'].clip(1, 5).astype(int)

    return df
