"""
QOT Testing Suite — Main Streamlit Application
Interactive parameter tuning for Quality Over Time scoring rules.
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from utils.config import DEFAULT_CONFIG, SPEC_ALIGNED_CONFIG, export_config, import_config
from utils.caching import get_cached_connection, load_temporal_metrics, load_production_qot
from utils.data_loader import get_data_status
from components.parameter_inputs import render_all_parameter_tabs
from components.validation import validate_config
from components.visualizations import (
    render_match_rate_summary,
    render_segment_match_rates,
    render_quality_match_rates,
    render_match_rate_by_year,
    render_qot_distribution,
    render_rule_impact,
    render_sub_quality_analysis,
    render_company_timeline,
)
from components.diff_table import render_diff_table
from components.parameter_reference import render_parameter_reference
from engine.scoring import run_scoring
from engine.spread import apply_spread_quality
from engine.compare import compute_all_comparisons
from engine.writer import write_calculated_qot, save_config
from pipeline.build_metrics import build_temporal_metrics


def init_session_state():
    """Initialize session state defaults."""
    if 'config' not in st.session_state:
        st.session_state.config = DEFAULT_CONFIG.copy()
    if 'results' not in st.session_state:
        st.session_state.results = None
    if 'experiments' not in st.session_state:
        st.session_state.experiments = []


def run_scoring_pipeline():
    """Load data, run scoring, compare against production."""
    df = load_temporal_metrics()
    if df is None:
        st.error("No data available. Click 'Refresh Data' first.")
        return

    # Load production qot if needed for qot_table baseline
    production_qot = None
    if st.session_state.config.get('baseline_strategy') == 'qot_table':
        conn = get_cached_connection()
        if conn is None:
            st.error("No database connection. Required for QOT Table baseline.")
            return
        production_qot = load_production_qot(conn)

    with st.spinner("Running scoring engine..."):
        scored = run_scoring(df, st.session_state.config, production_qot=production_qot)

    with st.spinner("Applying temporal spreading..."):
        scored = apply_spread_quality(scored)

    with st.spinner("Comparing against production DB..."):
        conn = get_cached_connection()
        if conn is None:
            st.error("No database connection. Check your .env file.")
            return
        results = compute_all_comparisons(scored, conn)

    st.session_state.results = results
    st.success(
        f"Scoring complete! Match rate: {results['qot_table']['overall_match_rate']:.1f}% "
        f"({results['qot_table']['delta_from_baseline']:+.2f}% vs baseline)"
    )


def main():
    st.set_page_config(
        layout="wide",
        page_title="QOT Testing Suite",
        page_icon="📊",
    )

    init_session_state()

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("QOT Testing Suite")

        # Data management
        st.subheader("Data")
        status = get_data_status()
        if status['exists']:
            st.caption(
                f"Last refresh: {status['last_modified'].strftime('%Y-%m-%d %H:%M')}\n\n"
                f"Records: {status['record_count']:,}"
            )
        else:
            st.warning("No data file found. Click Refresh Data.")

        if st.button("Refresh Data", use_container_width=True):
            conn = get_cached_connection()
            if conn is None:
                st.error("No database connection.")
            else:
                df = build_temporal_metrics(conn)
                st.cache_data.clear()
                st.success(f"Built {len(df):,} records")
                st.rerun()

        st.divider()

        # Validation
        errors = validate_config(st.session_state.config)
        if errors:
            st.error(f"{len(errors)} validation error(s)")
            for e in errors:
                st.caption(f"• {e}")
        else:
            st.success("Config valid")

        # Run scoring
        can_run = len(errors) == 0 and status['exists']
        if st.button("Run Scoring", use_container_width=True, disabled=not can_run, type="primary"):
            run_scoring_pipeline()

        st.divider()

        # Config management
        st.subheader("Config")

        # Preset selector
        preset = st.selectbox("Config Preset", ["Custom", "Spec-Aligned (2026)", "Legacy Default"])
        if preset == "Spec-Aligned (2026)" and st.session_state.config.get('use_spec_pipeline') != True:
            st.session_state.config = SPEC_ALIGNED_CONFIG.copy()
            st.session_state.results = None
            st.rerun()
        elif preset == "Legacy Default" and st.session_state.config.get('baseline_strategy') != 'quality_table':
            st.session_state.config = DEFAULT_CONFIG.copy()
            st.session_state.results = None
            st.rerun()

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Reset", use_container_width=True):
                st.session_state.config = DEFAULT_CONFIG.copy()
                st.session_state.results = None
                st.rerun()
        with col2:
            config_str = export_config(st.session_state.config, "json")
            st.download_button("Export", config_str, "qot_config.json", "application/json", use_container_width=True)
        with col3:
            uploaded = st.file_uploader("Import", type=['json', 'yaml'], label_visibility='collapsed', key='config_upload')
            if uploaded is not None:
                fmt = 'yaml' if uploaded.name.endswith(('.yaml', '.yml')) else 'json'
                st.session_state.config = import_config(uploaded.read().decode(), fmt)
                st.rerun()

        # Experiments
        if st.session_state.results is not None:
            st.divider()
            st.subheader("Experiments")
            exp_name = st.text_input("Experiment name", key='exp_name')
            if st.button("Save Experiment", use_container_width=True) and exp_name:
                st.session_state.experiments.append({
                    'name': exp_name,
                    'match_rate': st.session_state.results['qot_table']['overall_match_rate'],
                    'config': st.session_state.config.copy(),
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                })
                st.success(f"Saved: {exp_name}")

            for exp in st.session_state.experiments:
                st.caption(f"**{exp['name']}** — {exp['match_rate']:.1f}% ({exp['timestamp']})")

            # Publish to DB
            st.divider()
            st.subheader("Publish")
            publish_name = st.text_input("Config name", key='publish_name',
                                         placeholder="e.g. Baseline v2 - rev buckets")
            if st.button("Write to DB", use_container_width=True, type="secondary"):
                conn = get_cached_connection()
                if conn is None:
                    st.error("No database connection.")
                else:
                    scored = st.session_state.results['calculated_df']
                    match_rate = st.session_state.results['qot_table']['overall_match_rate']
                    config_hash, count = write_calculated_qot(
                        scored, st.session_state.config, conn
                    )
                    save_config(
                        st.session_state.config, conn,
                        name=publish_name or None, match_rate=match_rate
                    )
                    st.success(f"Wrote {count:,} records\n\nConfig: `{config_hash[:12]}...`")

        # Company lookup
        st.divider()
        st.subheader("Company Lookup")
        company_search = st.text_input("Search by name or ID", key='company_search')

    # ── Main Area ─────────────────────────────────────────────────────────
    tab_params, tab_results, tab_reference = st.tabs(["Parameters", "Results", "Reference"])

    with tab_params:
        st.session_state.config = render_all_parameter_tabs(st.session_state.config)

    with tab_results:
        if st.session_state.results is None:
            st.info("Configure parameters and click 'Run Scoring' to see results.")
        else:
            results = st.session_state.results
            qot_r = results['qot_table']
            comp_r = results['companies_table']
            calc_df = results['calculated_df']

            # Match rate summary
            render_match_rate_summary(qot_r, comp_r)

            st.divider()

            # Charts in columns
            col1, col2 = st.columns(2)
            with col1:
                render_segment_match_rates(qot_r['by_segment'])
            with col2:
                render_quality_match_rates(qot_r['by_quality'])

            col1, col2 = st.columns(2)
            with col1:
                render_match_rate_by_year(qot_r['by_year'])
            with col2:
                render_sub_quality_analysis(comp_r)

            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                render_qot_distribution(calc_df, qot_r)
            with col2:
                render_rule_impact(calc_df)

            st.divider()

            # Diff explorer
            st.subheader("Quality Score Comparison")
            render_diff_table(qot_r.get('full_comparison'), qot_r.get('mismatches'))

            # CSV download
            full_comp = qot_r.get('full_comparison')
            if full_comp is not None and len(full_comp) > 0:
                csv_cols = ['company_name', 'company_id', 'segment', 'year',
                            'companies_quality', 'companies_sub_quality',
                            'db_qot', 'calculated_qot', 'diff', 'direction',
                            'last_rule_applied']
                csv_cols = [c for c in csv_cols if c in full_comp.columns]
                csv_data = full_comp[csv_cols].sort_values(
                    ['company_name', 'year'], ascending=[True, True]
                ).to_csv(index=False)
                st.download_button(
                    "Download Results CSV",
                    csv_data,
                    "qot_comparison.csv",
                    "text/csv",
                    use_container_width=True,
                )

            st.divider()

            # Company timeline
            st.subheader("Company Timeline")
            if company_search:
                try:
                    cid = int(company_search)
                    company_data = calc_df[calc_df['company_id'] == cid]
                except ValueError:
                    company_data = calc_df[calc_df['company_name'].str.contains(company_search, case=False, na=False)]

                if len(company_data) > 0:
                    # If multiple companies matched by name, let user pick
                    unique_companies = company_data[['company_id', 'company_name']].drop_duplicates()
                    if len(unique_companies) > 1:
                        selected = st.selectbox(
                            "Multiple matches — select company",
                            unique_companies['company_id'].tolist(),
                            format_func=lambda x: unique_companies[unique_companies['company_id'] == x]['company_name'].iloc[0],
                        )
                        company_data = company_data[company_data['company_id'] == selected]

                    conn = get_cached_connection()
                    db_qot = load_production_qot(conn) if conn else None
                    render_company_timeline(company_data, db_qot)
                else:
                    st.warning("No company found matching your search.")
            else:
                st.caption("Enter a company name or ID in the sidebar to view its timeline.")

    with tab_reference:
        render_parameter_reference()


if __name__ == "__main__":
    main()
