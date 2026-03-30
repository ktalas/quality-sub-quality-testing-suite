"""
Parameter input tabs: 8 tabs matching the PRD categories.
Each render function returns a dict of updated parameter values.
"""
import streamlit as st
from utils.config import DEFAULT_CONFIG


def render_all_parameter_tabs(config: dict) -> dict:
    """Render all 10 parameter tabs and return merged config."""
    tabs = st.tabs([
        "1. Base Quality", "2. Revenue Upgrades", "3. Valuation Upgrades",
        "4. Downgrades", "5. Segment Rules", "6. Acquisition",
        "7. Tier 1 VC", "8. Advanced Rules", "9. Q5 Validation",
        "10. Public Co.",
    ])

    updated = config.copy()

    with tabs[0]:
        updated.update(_render_base_quality(config))
    with tabs[1]:
        updated.update(_render_revenue_upgrades(config))
    with tabs[2]:
        updated.update(_render_valuation_upgrades(config))
    with tabs[3]:
        updated.update(_render_downgrades(config))
    with tabs[4]:
        updated.update(_render_segment_rules(config))
    with tabs[5]:
        updated.update(_render_acquisition(config))
    with tabs[6]:
        updated.update(_render_tier1_vc(config))
    with tabs[7]:
        updated.update(_render_advanced(config))
    with tabs[8]:
        updated.update(_render_q5_validation(config))
    with tabs[9]:
        updated.update(_render_public_company(config))

    return updated


def _render_base_quality(config):
    st.subheader("Base Quality Assignment")
    p = {}

    # Baseline strategy selector
    strategy_options = {
        "quality_table": "Quality Table (Default) — stretch current quality_score across all years",
        "mosaic_only": "Mosaic Score Only — derive quality from mosaic thresholds",
        "qot_table": "QOT Table — use production qot values as starting point",
        "blank_slate": "Blank Slate — all companies start at Q1, rules build quality up",
    }
    current = config.get('baseline_strategy', 'quality_table')
    keys = list(strategy_options.keys())
    p['baseline_strategy'] = st.selectbox(
        "Baseline Strategy",
        options=keys,
        format_func=lambda x: strategy_options[x],
        index=keys.index(current) if current in keys else 0,
    )

    if p['baseline_strategy'] == 'quality_table':
        st.caption("Uses companies.quality_score (static, 1-5) applied to all historical years.")
    elif p['baseline_strategy'] == 'mosaic_only':
        st.caption("Derives quality from mosaic_score using the threshold/floor settings below. No mosaic = Q1.")
    elif p['baseline_strategy'] == 'qot_table':
        st.caption("Uses production qot table values directly. Missing company-years fall back to quality_score. Requires DB connection.")
    elif p['baseline_strategy'] == 'blank_slate':
        st.caption("Every company-year starts at Q1. Quality is built entirely by subsequent rules (sub_quality, mosaic, revenue, etc.).")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        p['upgrade_hot_to_5'] = st.checkbox("Upgrade Hot → Q5", value=config.get('upgrade_hot_to_5', True))
        p['upgrade_iconic_to_5'] = st.checkbox("Upgrade Iconic → Q5", value=config.get('upgrade_iconic_to_5', True))
    with col2:
        st.markdown("**Sub-quality mapping:**")
        st.markdown("- Hot = currently highest quality\n- Iconic = historically achieved Q5")

    st.divider()
    st.subheader("Mosaic Score Floors")

    col1, col2, col3 = st.columns(3)
    with col1:
        p['mosaic_900_threshold'] = st.number_input("Mosaic threshold (top)", value=config.get('mosaic_900_threshold', 900.0), step=10.0)
        p['mosaic_900_floor'] = st.slider("Quality floor", 1, 5, config.get('mosaic_900_floor', 4), key='m900f')
    with col2:
        p['mosaic_750_threshold'] = st.number_input("Mosaic threshold (mid)", value=config.get('mosaic_750_threshold', 750.0), step=10.0)
        p['mosaic_750_floor'] = st.slider("Quality floor", 1, 5, config.get('mosaic_750_floor', 3), key='m750f')
    with col3:
        p['mosaic_650_threshold'] = st.number_input("Mosaic threshold (low)", value=config.get('mosaic_650_threshold', 650.0), step=10.0)
        p['mosaic_650_floor'] = st.slider("Quality floor", 1, 5, config.get('mosaic_650_floor', 2), key='m650f')

    return p


def _render_revenue_upgrades(config):
    st.subheader("Revenue-Based Upgrades")
    p = {}

    BUCKET_LABELS = {
        "0_10m": "$0 – $10M",
        "10m_30m": "$10M – $30M",
        "30m_50m": "$30M – $50M",
        "50m_200m": "$50M – $200M",
        "200m_500m": "$200M – $500M",
        "500m_1b": "$500M – $1B",
        "1b_3b": "$1B – $3B",
        "3b_10b": "$3B – $10B",
        "10b_plus": "$10B+",
    }

    p['enable_revenue_upgrade'] = st.checkbox(
        "Enable revenue upgrades", value=config.get('enable_revenue_upgrade', False)
    )

    if p['enable_revenue_upgrade']:
        p['rev_upgrade_public_only'] = st.checkbox(
            "Apply only to Public companies", value=config.get('rev_upgrade_public_only', False)
        )

        st.divider()
        st.caption("Each bucket adds +1 to quality if the growth threshold is met. Pick 1-year or 3-year growth per bucket.")

        for suffix, label in BUCKET_LABELS.items():
            key = f'rev_bucket_{suffix}'
            bucket = config.get(key, {})

            col_enable, col_period, col_growth = st.columns([2, 1.5, 1.5])
            with col_enable:
                enabled = st.checkbox(
                    label, value=bucket.get('enabled', False), key=f'{key}_en'
                )
            with col_period:
                period = st.selectbox(
                    "Period", ["1y", "3y"],
                    index=0 if bucket.get('growth_period', '3y') == '1y' else 1,
                    key=f'{key}_per', disabled=not enabled
                )
            with col_growth:
                growth = st.number_input(
                    "Min growth", value=bucket.get('growth_threshold', 0.30),
                    step=0.05, format="%.2f", key=f'{key}_gr', disabled=not enabled
                )

            p[key] = {
                "enabled": enabled,
                "growth_period": period,
                "growth_threshold": growth,
            }

        st.divider()
        p['public_rev_upgrade_enabled'] = st.checkbox(
            "Enable separate public company rule (legacy)",
            value=config.get('public_rev_upgrade_enabled', False)
        )
        if p['public_rev_upgrade_enabled']:
            st.caption("Flat rule: public companies with min revenue + growth get upgraded. Separate from the bucket system above.")
            col1, col2 = st.columns(2)
            with col1:
                p['public_rev_upgrade_min_revenue'] = st.number_input(
                    "Public min revenue (USD)", value=config.get('public_rev_upgrade_min_revenue', 5_000_000_000),
                    step=500_000_000, format="%d"
                )
            with col2:
                p['public_rev_upgrade_growth_threshold'] = st.number_input(
                    "Public min growth", value=config.get('public_rev_upgrade_growth_threshold', 0.20),
                    step=0.05, format="%.2f"
                )

    return p


def _render_valuation_upgrades(config):
    st.subheader("Valuation-Based Upgrades")
    p = {}

    col1, col2 = st.columns(2)
    with col1:
        p['enable_unicorn_upgrade'] = st.checkbox("Enable unicorn floor", value=config.get('enable_unicorn_upgrade', False))
        if p['enable_unicorn_upgrade']:
            p['unicorn_upgrade_quality_floor'] = st.slider("Unicorn quality floor", 1, 5, config.get('unicorn_upgrade_quality_floor', 4), key='uqf')

    with col2:
        p['enable_decacorn_upgrade'] = st.checkbox("Enable decacorn floor", value=config.get('enable_decacorn_upgrade', False))
        if p['enable_decacorn_upgrade']:
            p['decacorn_upgrade_quality_floor'] = st.slider("Decacorn quality floor", 1, 5, config.get('decacorn_upgrade_quality_floor', 5), key='dqf')

    st.divider()
    p['enable_val_growth_upgrade'] = st.checkbox("Enable valuation growth upgrade", value=config.get('enable_val_growth_upgrade', False))
    if p['enable_val_growth_upgrade']:
        col1, col2, col3 = st.columns(3)
        with col1:
            p['val_growth_threshold'] = st.number_input(
                "3yr growth threshold", value=config.get('val_growth_threshold', 2.0),
                step=0.1, format="%.1f"
            )
        with col2:
            p['val_growth_upgrade_target'] = st.slider("Upgrade to quality", 1, 5, config.get('val_growth_upgrade_target', 5), key='vgut')
        with col3:
            p['require_revenue_validation'] = st.checkbox("Require revenue validation", value=config.get('require_revenue_validation', False))
            if p['require_revenue_validation']:
                p['val_upgrade_min_revenue'] = st.number_input(
                    "Min revenue (USD)", value=config.get('val_upgrade_min_revenue', 500_000_000),
                    step=100_000_000, format="%d", key='vumr'
                )

    return p


def _render_downgrades(config):
    st.subheader("Downgrade Rules")
    p = {}

    p['enable_revenue_decline_downgrade'] = st.checkbox(
        "Enable revenue decline downgrade", value=config.get('enable_revenue_decline_downgrade', False)
    )
    if p['enable_revenue_decline_downgrade']:
        col1, col2 = st.columns(2)
        with col1:
            p['rev_decline_threshold'] = st.number_input(
                "Revenue decline threshold (negative)", value=config.get('rev_decline_threshold', -0.20),
                step=0.05, format="%.2f"
            )
        with col2:
            p['rev_decline_segments'] = st.multiselect(
                "Apply to segments",
                ['VC', 'Growth', 'Public', 'PE', 'Acquired', 'Other'],
                default=config.get('rev_decline_segments', ['Public'])
            )

    st.divider()
    p['enable_stagnation_downgrade'] = st.checkbox(
        "Enable stagnation downgrade", value=config.get('enable_stagnation_downgrade', False)
    )
    if p['enable_stagnation_downgrade']:
        col1, col2, col3 = st.columns(3)
        with col1:
            p['rev_stagnation_years_threshold'] = st.number_input(
                "Rev stagnation years", value=config.get('rev_stagnation_years_threshold', 5),
                min_value=1, max_value=20, step=1
            )
        with col2:
            p['val_stagnation_years_threshold'] = st.number_input(
                "Val stagnation years", value=config.get('val_stagnation_years_threshold', 5),
                min_value=1, max_value=20, step=1
            )
        with col3:
            p['stagnation_downgrade_amount'] = st.number_input(
                "Downgrade amount", value=config.get('stagnation_downgrade_amount', 1),
                min_value=1, max_value=4, step=1
            )

    return p


def _render_segment_rules(config):
    st.subheader("Segment Rules")
    p = {}

    p['enable_public_to_pe_downgrade'] = st.checkbox(
        "Downgrade on Public → PE transition", value=config.get('enable_public_to_pe_downgrade', True)
    )
    if p['enable_public_to_pe_downgrade']:
        col1, col2 = st.columns(2)
        with col1:
            p['public_to_pe_min_quality'] = st.slider("Min quality to trigger", 1, 5, config.get('public_to_pe_min_quality', 4), key='p2pmq')
        with col2:
            p['public_to_pe_downgrade_amount'] = st.number_input(
                "Downgrade amount", value=config.get('public_to_pe_downgrade_amount', 1),
                min_value=1, max_value=4, step=1, key='p2pda'
            )

    st.divider()
    p['enable_pe_deal_decline_downgrade'] = st.checkbox(
        "Downgrade PE on deal activity decline", value=config.get('enable_pe_deal_decline_downgrade', False)
    )
    if p['enable_pe_deal_decline_downgrade']:
        p['pe_deal_decline_threshold'] = st.number_input(
            "Deal decline threshold", value=config.get('pe_deal_decline_threshold', -0.50),
            step=0.1, format="%.2f"
        )

    st.divider()
    p['enable_taken_private_cap'] = st.checkbox(
        "Cap quality at Q3 for taken-private companies", value=config.get('enable_taken_private_cap', False)
    )

    return p


def _render_acquisition(config):
    st.subheader("Acquisition Rules")
    p = {}

    p['enable_acquisition_degradation'] = st.checkbox(
        "Enable acquisition quality degradation", value=config.get('enable_acquisition_degradation', True)
    )
    if p['enable_acquisition_degradation']:
        col1, col2 = st.columns(2)
        with col1:
            p['acquisition_degradation_delay'] = st.number_input(
                "Years after acquisition before degradation",
                value=config.get('acquisition_degradation_delay', 2),
                min_value=0, max_value=10, step=1
            )
        with col2:
            p['acquisition_degradation_target'] = st.slider(
                "Degrade to quality", 1, 5, config.get('acquisition_degradation_target', 4), key='adt'
            )

    return p


def _render_tier1_vc(config):
    from utils.config import DEFAULT_TIER_1_VCS

    st.subheader("Tier 1 VC Rules")
    st.caption("Add +1 quality point for companies with Tier 1 VC involvement at selected funding stages.")
    p = {}

    p['enable_tier1_vc_upgrade'] = st.checkbox(
        "Enable Tier 1 VC upgrade", value=config.get('enable_tier1_vc_upgrade', False)
    )
    if p['enable_tier1_vc_upgrade']:
        # Stage selection
        st.markdown("**Funding stages to upgrade (+1 point each):**")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            p['tier1_vc_stage_seed'] = st.checkbox(
                "Seed", value=config.get('tier1_vc_stage_seed', False), key='t1_seed')
            p['tier1_vc_stage_series_a'] = st.checkbox(
                "Series A", value=config.get('tier1_vc_stage_series_a', False), key='t1_a')
        with col2:
            p['tier1_vc_stage_series_b'] = st.checkbox(
                "Series B", value=config.get('tier1_vc_stage_series_b', False), key='t1_b')
            p['tier1_vc_stage_series_c'] = st.checkbox(
                "Series C", value=config.get('tier1_vc_stage_series_c', False), key='t1_c')
        with col3:
            p['tier1_vc_stage_series_d'] = st.checkbox(
                "Series D", value=config.get('tier1_vc_stage_series_d', False), key='t1_d')
            p['tier1_vc_stage_late'] = st.checkbox(
                "Late Stage (E+)", value=config.get('tier1_vc_stage_late', False), key='t1_late')
        with col4:
            p['tier1_vc_stage_growth_equity'] = st.checkbox(
                "Growth Equity", value=config.get('tier1_vc_stage_growth_equity', False), key='t1_ge')
            p['tier1_vc_stage_pe'] = st.checkbox(
                "PE", value=config.get('tier1_vc_stage_pe', False), key='t1_pe')

        # Editable VC list
        st.markdown("**Tier 1 VC Firms:**")
        current_list = config.get('tier1_vc_list') or DEFAULT_TIER_1_VCS
        vc_text = st.text_area(
            "Edit the list (one firm per line). Add or remove firms as needed.",
            value='\n'.join(current_list),
            height=200,
            key='t1_vc_list_input',
        )
        parsed_list = [v.strip() for v in vc_text.strip().split('\n') if v.strip()]
        p['tier1_vc_list'] = parsed_list if parsed_list != DEFAULT_TIER_1_VCS else None

        if parsed_list != DEFAULT_TIER_1_VCS:
            added = set(parsed_list) - set(DEFAULT_TIER_1_VCS)
            removed = set(DEFAULT_TIER_1_VCS) - set(parsed_list)
            if added:
                st.caption(f"Added: {', '.join(sorted(added))}")
            if removed:
                st.caption(f"Removed: {', '.join(sorted(removed))}")
            if st.button("Reset to defaults", key='t1_reset_vc'):
                p['tier1_vc_list'] = None
                st.rerun()

    return p


def _render_q5_validation(config):
    st.subheader("Q5 Validation Guards")
    st.caption("Rules that prevent companies from reaching or keeping Q5 without sufficient fundamentals.")
    p = {}

    # Revenue declining exclusion
    p['enable_rev_declining_exclusion'] = st.checkbox(
        "Revenue declining companies cannot be Q5",
        value=config.get('enable_rev_declining_exclusion', False)
    )

    st.divider()

    # Decacorn revenue validation
    p['enable_decacorn_revenue_validation'] = st.checkbox(
        "Decacorn revenue validation",
        value=config.get('enable_decacorn_revenue_validation', False)
    )
    if p['enable_decacorn_revenue_validation']:
        st.markdown("**PE Decacorns ($10B+ valuation)**")
        p['decacorn_pe_rev_growth_threshold'] = st.number_input(
            "Required revenue growth", value=config.get('decacorn_pe_rev_growth_threshold', 0.75),
            step=0.05, format="%.2f", key='dprgt'
        )

        st.markdown("**Non-PE Decacorns**")
        col1, col2, col3 = st.columns(3)
        with col1:
            p['decacorn_nonpe_val_growth_threshold'] = st.number_input(
                "Val growth threshold", value=config.get('decacorn_nonpe_val_growth_threshold', 0.30),
                step=0.05, format="%.2f", key='dnvgt'
            )
        with col2:
            p['decacorn_nonpe_rev_growth_threshold'] = st.number_input(
                "Rev growth threshold", value=config.get('decacorn_nonpe_rev_growth_threshold', 0.30),
                step=0.05, format="%.2f", key='dnrgt'
            )
        with col3:
            p['decacorn_min_revenue'] = st.number_input(
                "Min revenue (USD)", value=config.get('decacorn_min_revenue', 500_000_000),
                step=50_000_000, format="%d", key='dmr'
            )

    st.divider()

    # Unicorn growth validation
    p['enable_unicorn_growth_validation'] = st.checkbox(
        "Unicorn growth validation",
        value=config.get('enable_unicorn_growth_validation', False)
    )
    if p['enable_unicorn_growth_validation']:
        col1, col2 = st.columns(2)
        with col1:
            p['unicorn_val_growth_threshold'] = st.number_input(
                "Val growth threshold", value=config.get('unicorn_val_growth_threshold', 0.75),
                step=0.05, format="%.2f", key='uvgt'
            )
        with col2:
            p['unicorn_min_revenue'] = st.number_input(
                "Min revenue (USD)", value=config.get('unicorn_min_revenue', 100_000_000),
                step=10_000_000, format="%d", key='umr'
            )

    return p


def _render_public_company(config):
    st.subheader("Public Company Fine-Tuning")
    st.caption("Rules from the baseline QOT calculator targeting public companies without sub_quality designations.")
    p = {}

    p['enable_public_low_growth_downgrade'] = st.checkbox(
        "Downgrade low-growth public companies", value=config.get('enable_public_low_growth_downgrade', True)
    )
    if p['enable_public_low_growth_downgrade']:
        col1, col2, col3 = st.columns(3)
        with col1:
            p['public_low_growth_threshold'] = st.number_input(
                "Growth threshold", value=config.get('public_low_growth_threshold', 0.05),
                step=0.01, format="%.2f", key='plgt'
            )
        with col2:
            p['public_low_growth_min_quality'] = st.slider(
                "Min quality to trigger", 1, 5, config.get('public_low_growth_min_quality', 4), key='plgmq'
            )
        with col3:
            p['public_low_growth_target'] = st.slider(
                "Downgrade to", 1, 5, config.get('public_low_growth_target', 3), key='plgdt'
            )

    st.divider()
    p['enable_public_large_rev_upgrade'] = st.checkbox(
        "Upgrade large-revenue Q1 public companies", value=config.get('enable_public_large_rev_upgrade', True)
    )
    if p['enable_public_large_rev_upgrade']:
        p['public_large_rev_threshold'] = st.number_input(
            "Min revenue (USD)", value=config.get('public_large_rev_threshold', 1_000_000_000),
            step=100_000_000, format="%d", key='plrt'
        )

    return p


def _render_advanced(config):
    st.subheader("Advanced Rules")
    st.caption("Rules ported from assign_quality.py covering edge cases and segment-specific logic.")
    p = {}

    # Exceptional valuation growth
    p['enable_exceptional_val_growth'] = st.checkbox(
        "Exceptional valuation growth → Q5 (non-PE)", value=config.get('enable_exceptional_val_growth', True)
    )
    if p['enable_exceptional_val_growth']:
        p['exceptional_val_growth_threshold'] = st.number_input(
            "3yr growth threshold", value=config.get('exceptional_val_growth_threshold', 2.0),
            step=0.1, format="%.1f", key='evgt'
        )

    st.divider()

    # PE hot rules
    p['enable_pe_hot_rules'] = st.checkbox(
        "PE-specific Q5 rules", value=config.get('enable_pe_hot_rules', True)
    )
    if p['enable_pe_hot_rules']:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**High-rev PE ($50B+ rev)**")
            p['pe_hot_rev_threshold_high'] = st.number_input(
                "Revenue threshold (USD)", value=config.get('pe_hot_rev_threshold_high', 50_000_000_000),
                step=5_000_000_000, format="%d", key='phrth'
            )
            p['pe_hot_growth_threshold_high'] = st.number_input(
                "Growth threshold", value=config.get('pe_hot_growth_threshold_high', 0.50),
                step=0.05, format="%.2f", key='phgth'
            )
        with col2:
            st.markdown("**Lower-rev PE ($20B+ rev)**")
            p['pe_hot_rev_threshold_low'] = st.number_input(
                "Revenue threshold (USD)", value=config.get('pe_hot_rev_threshold_low', 20_000_000_000),
                step=5_000_000_000, format="%d", key='phrtl'
            )
            p['pe_hot_growth_threshold_low'] = st.number_input(
                "Growth threshold", value=config.get('pe_hot_growth_threshold_low', 0.75),
                step=0.05, format="%.2f", key='phgtl'
            )

    st.divider()

    # Revenue growth upgrade
    p['enable_rev_growth_upgrade'] = st.checkbox(
        "Exceptional revenue growth → Q5", value=config.get('enable_rev_growth_upgrade', True)
    )
    if p['enable_rev_growth_upgrade']:
        col1, col2 = st.columns(2)
        with col1:
            p['rev_growth_upgrade_min_revenue'] = st.number_input(
                "Min revenue (USD)", value=config.get('rev_growth_upgrade_min_revenue', 100_000_000),
                step=10_000_000, format="%d", key='rgumr'
            )
        with col2:
            p['rev_growth_upgrade_threshold'] = st.number_input(
                "Growth threshold", value=config.get('rev_growth_upgrade_threshold', 1.50),
                step=0.1, format="%.2f", key='rgut'
            )

    st.divider()

    # Legacy rules
    col1, col2 = st.columns(2)
    with col1:
        p['enable_legacy_exclusion'] = st.checkbox(
            "Legacy companies cannot be Q5", value=config.get('enable_legacy_exclusion', True)
        )
    with col2:
        p['enable_legacy_penalty'] = st.checkbox(
            "Cap legacy company quality", value=config.get('enable_legacy_penalty', False)
        )
        if p['enable_legacy_penalty']:
            p['legacy_penalty_max_quality'] = st.slider(
                "Max quality for legacy", 1, 5, config.get('legacy_penalty_max_quality', 3), key='lpmq'
            )

    st.divider()

    # Valuation decline
    p['enable_val_decline_downgrade'] = st.checkbox(
        "VC valuation decline downgrade", value=config.get('enable_val_decline_downgrade', True)
    )
    if p['enable_val_decline_downgrade']:
        p['val_decline_threshold'] = st.number_input(
            "Decline threshold (negative)", value=config.get('val_decline_threshold', -0.30),
            step=0.05, format="%.2f", key='vdt'
        )

    # Growth segment stagnation
    p['enable_growth_rev_stagnation'] = st.checkbox(
        "Growth segment: revenue stagnation downgrade", value=config.get('enable_growth_rev_stagnation', True)
    )
    if p['enable_growth_rev_stagnation']:
        p['growth_rev_stagnation_years'] = st.number_input(
            "Years of stagnation", value=config.get('growth_rev_stagnation_years', 3),
            min_value=1, max_value=10, step=1, key='grsy'
        )

    st.divider()

    # Stagnant valuation + revenue check
    p['enable_stagnant_val_rev_check'] = st.checkbox(
        "Stagnant valuation requires revenue growth for Q5",
        value=config.get('enable_stagnant_val_rev_check', True)
    )
    if p['enable_stagnant_val_rev_check']:
        p['stagnant_val_threshold'] = st.number_input(
            "Valuation growth below this = stagnant", value=config.get('stagnant_val_threshold', 0.10),
            step=0.05, format="%.2f", key='svt'
        )

    # No recent funding check
    p['enable_no_recent_funding_check'] = st.checkbox(
        "Higher revenue bar for companies with no recent funding",
        value=config.get('enable_no_recent_funding_check', True)
    )
    if p['enable_no_recent_funding_check']:
        p['no_recent_funding_cutoff_year'] = st.number_input(
            "No deals since year", value=config.get('no_recent_funding_cutoff_year', 2022),
            min_value=2018, max_value=2026, step=1, key='nrfcy'
        )

    return p
