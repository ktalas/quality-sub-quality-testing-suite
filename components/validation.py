"""
Config validation: checks parameter constraints.
"""


def validate_config(config: dict) -> list[str]:
    """Returns list of error strings. Empty = valid."""
    errors = []

    # Baseline strategy must be valid
    strategy = config.get('baseline_strategy', 'quality_table')
    valid_strategies = ['quality_table', 'mosaic_only', 'qot_table', 'blank_slate']
    if strategy not in valid_strategies:
        errors.append(f"baseline_strategy must be one of {valid_strategies} (got '{strategy}')")

    # Quality values must be 1-5
    quality_keys = [
        'mosaic_900_floor', 'mosaic_750_floor', 'mosaic_650_floor',
        'rev_upgrade_target_quality', 'unicorn_upgrade_quality_floor',
        'decacorn_upgrade_quality_floor', 'val_growth_upgrade_target',
        'public_to_pe_min_quality', 'acquisition_degradation_target',
        'tier1_vc_upgrade_target', 'legacy_penalty_max_quality',
        'public_low_growth_min_quality', 'public_low_growth_target',
    ]
    for key in quality_keys:
        val = config.get(key)
        if val is not None and (val < 1 or val > 5):
            errors.append(f"{key} must be between 1 and 5 (got {val})")

    # Mosaic thresholds in descending order
    t900 = config.get('mosaic_900_threshold', 900)
    t750 = config.get('mosaic_750_threshold', 750)
    t650 = config.get('mosaic_650_threshold', 650)
    if not (t900 > t750 > t650):
        errors.append(f"Mosaic thresholds must be descending: {t900} > {t750} > {t650}")

    # Revenue thresholds sanity check (should be in USD, not millions)
    rev_keys = [
        'rev_upgrade_min_revenue', 'public_rev_upgrade_min_revenue',
        'val_upgrade_min_revenue', 'tier1_vc_min_valuation',
        'decacorn_min_revenue', 'unicorn_min_revenue',
        'pe_hot_rev_threshold_high', 'pe_hot_rev_threshold_low',
        'rev_growth_upgrade_min_revenue',
    ]
    for key in rev_keys:
        val = config.get(key)
        if val is not None and val < 1000:
            errors.append(f"{key} = {val} looks too low — values should be in USD (e.g., 1000000000 for $1B)")

    # Downgrade amount must be positive
    for key in ['stagnation_downgrade_amount', 'public_to_pe_downgrade_amount']:
        val = config.get(key)
        if val is not None and val < 1:
            errors.append(f"{key} must be >= 1 (got {val})")

    # Growth thresholds should be non-negative
    growth_keys = [
        'rev_upgrade_growth_threshold', 'public_rev_upgrade_growth_threshold',
        'val_growth_threshold', 'tier1_vc_growth_threshold',
        'exceptional_val_growth_threshold', 'rev_growth_upgrade_threshold',
        'pe_hot_growth_threshold_high', 'pe_hot_growth_threshold_low',
        'decacorn_pe_rev_growth_threshold', 'decacorn_nonpe_val_growth_threshold',
        'decacorn_nonpe_rev_growth_threshold', 'unicorn_val_growth_threshold',
    ]
    for key in growth_keys:
        val = config.get(key)
        if val is not None and val < 0:
            errors.append(f"{key} should be non-negative (got {val})")

    # Acquisition delay must be non-negative
    delay = config.get('acquisition_degradation_delay')
    if delay is not None and delay < 0:
        errors.append(f"acquisition_degradation_delay must be >= 0 (got {delay})")

    return errors
