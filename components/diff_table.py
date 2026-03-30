"""
Diff explorer: interactive comparison table showing calculated vs production QOT.
Defaults to current year, with option to view all years.
"""
import streamlit as st
import pandas as pd
from datetime import datetime


def render_diff_table(full_comparison: pd.DataFrame, mismatches: pd.DataFrame = None):
    """Filterable table comparing calculated QOT against production QOT table.

    Shows all records by default (not just mismatches), with the diff between
    calculated and DB scores. Defaults to current year only.
    """
    if full_comparison is None or len(full_comparison) == 0:
        st.info("No comparison data available.")
        return

    current_year = datetime.now().year

    # ── Year filter ──────────────────────────────────────────────────────
    available_years = sorted(full_comparison['year'].unique().tolist())

    col_toggle, col_year = st.columns([1, 2])
    with col_toggle:
        show_all_years = st.toggle("Show all years", value=False, key='diff_all_years')
    with col_year:
        if not show_all_years:
            # Default to current year if available, otherwise latest
            default_year = current_year if current_year in available_years else available_years[-1]
            default_idx = available_years.index(default_year)
            selected_year = st.selectbox(
                "Year", available_years, index=default_idx, key='diff_year'
            )
        else:
            selected_year = None

    # Apply year filter
    if show_all_years:
        filtered = full_comparison.copy()
    else:
        filtered = full_comparison[full_comparison['year'] == selected_year].copy()

    # ── Additional filters ───────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        view_options = ['All Records', 'Mismatches Only', 'Matches Only']
        selected_view = st.selectbox("Show", view_options, key='diff_view')

    with col2:
        if 'segment' in filtered.columns:
            segments = ['All'] + sorted(filtered['segment'].dropna().unique().tolist())
            selected_segment = st.selectbox("Segment", segments, key='diff_seg')
        else:
            selected_segment = 'All'

    with col3:
        directions = ['All', 'upgraded', 'downgraded', 'match']
        selected_direction = st.selectbox("Direction", directions, key='diff_dir')

    with col4:
        if 'last_rule_applied' in filtered.columns:
            rules = ['All'] + sorted(filtered['last_rule_applied'].dropna().unique().tolist())
            selected_rule = st.selectbox("Last Rule", rules, key='diff_rule')
        else:
            selected_rule = 'All'

    # Apply filters
    if selected_view == 'Mismatches Only':
        filtered = filtered[filtered['diff'] != 0]
    elif selected_view == 'Matches Only':
        filtered = filtered[filtered['diff'] == 0]

    if selected_segment != 'All' and 'segment' in filtered.columns:
        filtered = filtered[filtered['segment'] == selected_segment]
    if selected_direction != 'All' and 'direction' in filtered.columns:
        filtered = filtered[filtered['direction'] == selected_direction]
    if selected_rule != 'All' and 'last_rule_applied' in filtered.columns:
        filtered = filtered[filtered['last_rule_applied'] == selected_rule]

    # ── Summary metrics ──────────────────────────────────────────────────
    total_shown = len(filtered)
    matches_in_view = (filtered['diff'] == 0).sum() if total_shown > 0 else 0
    mismatches_in_view = total_shown - matches_in_view
    match_rate_in_view = (matches_in_view / total_shown * 100) if total_shown > 0 else 0

    year_label = "All Years" if show_all_years else str(selected_year)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(f"Match Rate ({year_label})", f"{match_rate_in_view:.1f}%")
    with m2:
        st.metric("Total Records", f"{total_shown:,}")
    with m3:
        st.metric("Matches", f"{matches_in_view:,}")
    with m4:
        st.metric("Mismatches", f"{mismatches_in_view:,}")

    # ── Display table ────────────────────────────────────────────────────
    display_cols = ['company_name', 'company_id', 'segment', 'year',
                    'companies_quality', 'companies_sub_quality',
                    'db_qot', 'calculated_qot', 'diff', 'direction',
                    'last_rule_applied']
    display_cols = [c for c in display_cols if c in filtered.columns]

    if total_shown == 0:
        st.info("No records match the selected filters.")
        return

    # Style: highlight mismatches
    def style_diff(val):
        if val > 0:
            return 'color: #4CAF50; font-weight: bold'
        elif val < 0:
            return 'color: #F44336; font-weight: bold'
        return 'color: #888'

    # Sort: Hot (sub_quality) first, then by db_qot descending, then by diff magnitude
    sort_cols = []
    sort_ascending = []
    filtered = filtered.copy()
    if 'companies_sub_quality' in filtered.columns:
        filtered['_hot_sort'] = (filtered['companies_sub_quality'] != 'Hot').astype(int)
        sort_cols.append('_hot_sort')
        sort_ascending.append(True)
    if 'db_qot' in filtered.columns:
        sort_cols.append('db_qot')
        sort_ascending.append(False)
    if 'diff' in filtered.columns:
        sort_cols.append('diff')
        sort_ascending.append(True)
    if sort_cols:
        filtered = filtered.sort_values(sort_cols, ascending=sort_ascending)
    display_df = filtered[display_cols]

    st.dataframe(
        display_df.style.applymap(style_diff, subset=['diff'] if 'diff' in display_cols else []),
        use_container_width=True,
        height=500,
    )

    # ── Breakdown stats ──────────────────────────────────────────────────
    if 'direction' in filtered.columns and mismatches_in_view > 0:
        st.caption("Mismatch Breakdown")
        col1, col2, col3 = st.columns(3)
        with col1:
            upgraded = (filtered['direction'] == 'upgraded').sum()
            st.metric("Upgraded (calc > db)", upgraded)
        with col2:
            downgraded = (filtered['direction'] == 'downgraded').sum()
            st.metric("Downgraded (calc < db)", downgraded)
        with col3:
            if 'diff' in filtered.columns:
                avg_diff = filtered[filtered['diff'] != 0]['diff'].mean()
                st.metric("Avg Mismatch", f"{avg_diff:+.2f}")
