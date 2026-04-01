"""
Config management: defaults, serialization, experiments.
"""
import json
import yaml

DEFAULT_TIER_1_VCS = [
    'Sequoia Capital', 'Andreessen Horowitz',
]

DEFAULT_TIER_2_VCS = [
    'Accel', 'Benchmark', 'Kleiner Perkins', 'GV', 'Greylock Partners',
    'Bessemer Venture Partners', 'Index Ventures', 'Lightspeed Venture Partners',
    'NEA', 'Founders Fund', 'General Catalyst', 'Tiger Global Management',
    'Insight Partners', 'Battery Ventures', 'Redpoint Ventures',
    'Matrix Partners', 'Union Square Ventures', 'First Round Capital',
    'Spark Capital', 'Thrive Capital', 'Coatue Management',
]

ALL_NAMED_VCS = DEFAULT_TIER_1_VCS + DEFAULT_TIER_2_VCS

# For backward compatibility (old code expects all 23 in one list)
TIER_1_VCS = ALL_NAMED_VCS

# Funding stages and the round names that map to each
FUNDING_STAGES = {
    "Seed": ['Angel', 'Pre-Seed', 'Seed', 'Angel - II', 'Angel - III', 'Pre-Seed - II',
             'Seed - II', 'Seed - III', 'Seed VC'],
    "Series A": ['Series A', 'Series A - II'],
    "Series B": ['Series B', 'Series B - II'],
    "Series C": ['Series C'],
    "Series D": ['Series D'],
    "Late Stage": ['Series E', 'Series F', 'Series G', 'Series H', 'Series I',
                   'Series J', 'Series K'],
    "Growth Equity": ['Growth Equity', 'Growth Equity - II', 'Growth Equity - III'],
    "PE": ['Private Equity', 'Private Equity - II', 'Private Equity - III',
           'Leveraged Buyout', 'Management Buyout'],
}

REVENUE_SOURCE_QUALITY = {
    "user": 1.0,
    "Polygon": 1.0,
    "CB Insights": 0.3,
    "calculated": 0.3,
    "privco": 0.3,
    "initial": 0.2,
    "OpenAI": 0.1,
}

# Quality mapping: companies.quality string -> numeric
QUALITY_STRING_TO_INT = {
    "Low": 1,
    "Medium": 2,
    "High": 3,
    "Top": 4,
}

DEFAULT_CONFIG = {
    # Baseline strategy
    "baseline_strategy": "quality_table",  # "quality_table" | "mosaic_only" | "qot_table" | "blank_slate"

    # 1. Base Quality
    "upgrade_hot_to_5": True,
    "upgrade_iconic_to_5": False,
    "mosaic_900_floor": 4,
    "mosaic_750_floor": 3,
    "mosaic_650_floor": 2,
    "mosaic_900_threshold": 900.0,
    "mosaic_750_threshold": 750.0,
    "mosaic_650_threshold": 650.0,

    # 2. Revenue Upgrades
    "enable_revenue_upgrade": False,
    "rev_upgrade_public_only": False,
    "rev_bucket_0_10m": {"enabled": False, "growth_period": "3y", "growth_threshold": 3.00},
    "rev_bucket_10m_30m": {"enabled": False, "growth_period": "3y", "growth_threshold": 2.50},
    "rev_bucket_30m_50m": {"enabled": False, "growth_period": "3y", "growth_threshold": 2.00},
    "rev_bucket_50m_200m": {"enabled": False, "growth_period": "3y", "growth_threshold": 1.50},
    "rev_bucket_200m_500m": {"enabled": False, "growth_period": "3y", "growth_threshold": 1.00},
    "rev_bucket_500m_1b": {"enabled": False, "growth_period": "3y", "growth_threshold": 0.60},
    "rev_bucket_1b_3b": {"enabled": False, "growth_period": "3y", "growth_threshold": 0.40},
    "rev_bucket_3b_10b": {"enabled": False, "growth_period": "3y", "growth_threshold": 0.30},
    "rev_bucket_10b_plus": {"enabled": False, "growth_period": "3y", "growth_threshold": 0.20},
    "public_rev_upgrade_enabled": False,
    "public_rev_upgrade_min_revenue": 5_000_000_000,
    "public_rev_upgrade_growth_threshold": 0.20,

    # 3. Valuation Upgrades
    "enable_unicorn_upgrade": False,
    "unicorn_upgrade_quality_floor": 4,
    "enable_decacorn_upgrade": False,
    "decacorn_upgrade_quality_floor": 5,
    "enable_val_growth_upgrade": False,
    "val_growth_threshold": 2.0,
    "val_growth_upgrade_target": 5,
    "require_revenue_validation": False,
    "val_upgrade_min_revenue": 500_000_000,

    # 4. Downgrade Rules
    "enable_revenue_decline_downgrade": False,
    "rev_decline_threshold": -0.20,
    "rev_decline_segments": ["Public"],
    "enable_stagnation_downgrade": False,
    "rev_stagnation_years_threshold": 5,
    "val_stagnation_years_threshold": 5,
    "stagnation_downgrade_amount": 1,

    # 5. Segment Rules
    "enable_public_to_pe_downgrade": False,
    "public_to_pe_min_quality": 4,
    "public_to_pe_downgrade_amount": 1,
    "enable_pe_deal_decline_downgrade": False,
    "pe_deal_decline_threshold": -0.50,
    "enable_taken_private_cap": True,

    # 6. Acquisition Rules
    "enable_acquisition_degradation": True,
    "acquisition_degradation_delay": 2,
    "acquisition_degradation_target": 4,

    # 7. Tier 1 VC Rules
    "enable_tier1_vc_upgrade": False,
    "tier1_vc_list": None,  # None = use DEFAULT_TIER_1_VCS; list overrides
    "tier1_vc_stage_seed": False,
    "tier1_vc_stage_series_a": False,
    "tier1_vc_stage_series_b": False,
    "tier1_vc_stage_series_c": False,
    "tier1_vc_stage_series_d": False,
    "tier1_vc_stage_late": False,
    "tier1_vc_stage_growth_equity": False,
    "tier1_vc_stage_pe": False,

    # 8. Advanced Rules
    "enable_exceptional_val_growth": False,
    "exceptional_val_growth_threshold": 2.0,
    "enable_pe_hot_rules": False,
    "pe_hot_rev_threshold_high": 50_000_000_000,
    "pe_hot_growth_threshold_high": 0.50,
    "pe_hot_rev_threshold_low": 20_000_000_000,
    "pe_hot_growth_threshold_low": 0.75,
    "enable_rev_growth_upgrade": False,
    "rev_growth_upgrade_min_revenue": 100_000_000,
    "rev_growth_upgrade_threshold": 1.50,
    "enable_legacy_exclusion": False,
    "enable_legacy_penalty": False,
    "legacy_penalty_max_quality": 3,
    "enable_val_decline_downgrade": False,
    "val_decline_threshold": -0.30,
    "enable_growth_rev_stagnation": False,
    "growth_rev_stagnation_years": 3,
    "enable_stagnant_val_rev_check": False,
    "stagnant_val_threshold": 0.10,
    "enable_no_recent_funding_check": False,
    "no_recent_funding_cutoff_year": 2022,

    # 9. Q5 Validation Guards
    "enable_rev_declining_exclusion": False,
    "enable_decacorn_revenue_validation": False,
    "decacorn_pe_rev_growth_threshold": 0.75,
    "decacorn_nonpe_val_growth_threshold": 0.30,
    "decacorn_nonpe_rev_growth_threshold": 0.30,
    "decacorn_min_revenue": 500_000_000,
    "enable_unicorn_growth_validation": False,
    "unicorn_val_growth_threshold": 0.75,
    "unicorn_min_revenue": 100_000_000,

    # 10. Public Company Fine-Tuning (from baseline)
    "enable_public_low_growth_downgrade": True,
    "public_low_growth_threshold": 0.05,
    "public_low_growth_min_quality": 4,
    "public_low_growth_target": 3,
    "enable_public_large_rev_upgrade": True,
    "public_large_rev_threshold": 1_000_000_000,
}


SPEC_ALIGNED_CONFIG = {
    **DEFAULT_CONFIG,

    # Baseline: mosaic-based, not quality_table stretch
    "baseline_strategy": "mosaic_only",

    # Mosaic thresholds per spec: 850/650/500 (not 900/750/650)
    "mosaic_900_threshold": 850.0,
    "mosaic_750_threshold": 650.0,
    "mosaic_650_threshold": 500.0,

    # Hot/Iconic are earned through Q5 promotion, not auto-assigned
    "upgrade_hot_to_5": False,
    "upgrade_iconic_to_5": False,

    # Enable no-mosaic fallback (new rule)
    "enable_no_mosaic_fallback": True,

    # Enable consolidated Q5 promotions (new rule)
    "enable_q5_promotions": True,

    # Q5 validation guards — all enabled
    "enable_stagnant_val_rev_check": True,
    "enable_legacy_exclusion": True,
    "enable_rev_declining_exclusion": True,

    # Drop rules — all enabled per spec
    "enable_val_decline_downgrade": True,
    "enable_growth_rev_stagnation": True,
    "enable_revenue_decline_downgrade": True,
    "enable_stagnation_downgrade": True,
    "enable_pe_deal_decline_downgrade": True,
    "enable_public_to_pe_downgrade": True,
    "enable_taken_private_cap": True,

    # Segment-aware stagnation (new behavior)
    "stagnation_segment_aware": True,
    "vc_val_stagnation_years": 5,
    "growth_rev_stagnation_years": 3,
    "public_rev_stagnation_years": 5,

    # Disable non-spec rules
    "enable_public_low_growth_downgrade": False,
    "enable_public_large_rev_upgrade": False,
    "enable_no_recent_funding_check": False,

    # Disable old scattered rules (subsumed by q5_promotions)
    "enable_exceptional_val_growth": False,
    "enable_pe_hot_rules": False,
    "enable_rev_growth_upgrade": False,
    "enable_tier1_vc_upgrade": False,
    "enable_revenue_upgrade": False,
    "public_rev_upgrade_enabled": False,
    "enable_unicorn_upgrade": False,
    "enable_decacorn_upgrade": False,
    "enable_val_growth_upgrade": False,
    "enable_decacorn_revenue_validation": False,
    "enable_unicorn_growth_validation": False,

    # Current year manual override
    "enable_current_year_override": True,

    # Sub-quality auto-assignment
    "enable_sub_quality_assignment": True,
    "sub_quality_recency_years": 5,
    "sub_quality_growth_percentile": 0.75,
    "incumbent_to_legacy_years": 5,
    "iconic_longevity_years": 10,
    "iconic_revenue_scale": 1_000_000_000,
    "iconic_market_score": 900,

    # Use the spec pipeline
    "use_spec_pipeline": True,
}


def export_config(config: dict, fmt: str = "json") -> str:
    if fmt == "yaml":
        return yaml.dump(config, default_flow_style=False, sort_keys=False)
    return json.dumps(config, indent=2)


def import_config(data: str, fmt: str = "json") -> dict:
    if fmt == "yaml":
        loaded = yaml.safe_load(data)
    else:
        loaded = json.loads(data)
    # Merge with defaults so missing keys get filled
    merged = DEFAULT_CONFIG.copy()
    merged.update(loaded)
    return merged
