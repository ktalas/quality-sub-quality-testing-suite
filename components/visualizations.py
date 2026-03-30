"""
Plotly visualizations for the QOT Testing Suite.
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np


def render_match_rate_summary(qot_results: dict, companies_results: dict):
    """Render st.metric cards for match rates."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "QOT Table Match",
            f"{qot_results['overall_match_rate']:.1f}%",
            f"{qot_results['delta_from_baseline']:+.2f}% vs baseline",
        )
    with col2:
        st.metric("Records Compared", f"{qot_results['total_compared']:,}")
    with col3:
        st.metric(
            "Companies Match",
            f"{companies_results['quality_match_rate']:.1f}%",
        )
    with col4:
        st.metric("Companies Compared", f"{companies_results['total_compared']:,}")


def render_segment_match_rates(by_segment: dict):
    """Bar chart of match rates by segment."""
    if not by_segment:
        st.info("No segment data available.")
        return

    segments = list(by_segment.keys())
    rates = list(by_segment.values())

    fig = go.Figure(go.Bar(
        x=segments, y=rates,
        text=[f"{r:.1f}%" for r in rates],
        textposition='auto',
        marker_color=['#2196F3' if r >= 80 else '#FF9800' if r >= 60 else '#F44336' for r in rates],
    ))
    fig.update_layout(
        title="Match Rate by Segment",
        yaxis_title="Match Rate (%)",
        yaxis_range=[0, 100],
        height=350,
    )
    fig.add_hline(y=82.25, line_dash="dash", line_color="gray", annotation_text="Baseline 82.25%")
    st.plotly_chart(fig, use_container_width=True)


def render_quality_match_rates(by_quality: dict):
    """Bar chart of match rates by quality level."""
    if not by_quality:
        st.info("No quality-level data available.")
        return

    levels = sorted(by_quality.keys())
    rates = [by_quality[q] for q in levels]

    fig = go.Figure(go.Bar(
        x=[f"Q{q}" for q in levels], y=rates,
        text=[f"{r:.1f}%" for r in rates],
        textposition='auto',
        marker_color='#4CAF50',
    ))
    fig.update_layout(
        title="Match Rate by Quality Level",
        yaxis_title="Match Rate (%)",
        yaxis_range=[0, 100],
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_match_rate_by_year(by_year: dict):
    """Line chart of match rate over time."""
    if not by_year:
        st.info("No yearly data available.")
        return

    years = sorted(by_year.keys())
    rates = [by_year[y] for y in years]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years, y=rates,
        mode='lines+markers',
        name='Match Rate',
        line=dict(color='#2196F3', width=2),
    ))
    fig.add_hline(y=82.25, line_dash="dash", line_color="gray", annotation_text="Baseline")
    fig.update_layout(
        title="Match Rate by Year",
        xaxis_title="Year",
        yaxis_title="Match Rate (%)",
        yaxis_range=[0, 100],
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_qot_distribution(calculated_df: pd.DataFrame, qot_results: dict):
    """Side-by-side histogram of calculated vs DB QOT distribution."""
    calc_counts = calculated_df['calculated_qot'].value_counts().sort_index()

    mismatches = qot_results.get('mismatches', pd.DataFrame())
    # Reconstruct DB distribution from matched + mismatched records
    if 'db_qot' in qot_results.get('mismatches', pd.DataFrame()).columns:
        # Get all compared records
        merged_count = qot_results['total_compared']
        # We need the full joined data — approximate from mismatches + match rate
        db_counts = pd.Series(dtype=int)
        for q in range(1, 6):
            # Count from mismatches
            db_q = len(mismatches[mismatches['db_qot'] == q]) if len(mismatches) > 0 else 0
            db_counts[q] = db_q
    else:
        db_counts = pd.Series(dtype=int)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[f"Q{q}" for q in range(1, 6)],
        y=[calc_counts.get(q, 0) for q in range(1, 6)],
        name='Calculated',
        marker_color='#2196F3',
    ))
    if len(db_counts) > 0:
        fig.add_trace(go.Bar(
            x=[f"Q{q}" for q in range(1, 6)],
            y=[db_counts.get(q, 0) for q in range(1, 6)],
            name='DB (mismatches only)',
            marker_color='#FF9800',
        ))

    fig.update_layout(
        title="QOT Distribution",
        xaxis_title="Quality Level",
        yaxis_title="Count",
        barmode='group',
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_rule_impact(calculated_df: pd.DataFrame):
    """Horizontal bar chart showing how many records each rule touched."""
    # Flatten rules_applied lists
    all_rules = []
    for rules_list in calculated_df['rules_applied']:
        if isinstance(rules_list, list):
            all_rules.extend(rules_list)

    if not all_rules:
        st.info("No rules were applied.")
        return

    rule_counts = pd.Series(all_rules).value_counts()

    fig = go.Figure(go.Bar(
        y=rule_counts.index,
        x=rule_counts.values,
        orientation='h',
        text=rule_counts.values,
        textposition='auto',
        marker_color='#9C27B0',
    ))
    fig.update_layout(
        title="Rule Impact (records modified per rule)",
        xaxis_title="Records Modified",
        height=max(400, len(rule_counts) * 30),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_sub_quality_analysis(companies_results: dict):
    """Bar chart showing Hot/Iconic/Legacy detection accuracy."""
    breakdown = companies_results.get('sub_quality_breakdown', {})
    if not breakdown:
        st.info("No sub-quality data available.")
        return

    labels = list(breakdown.keys())
    rates = [breakdown[k]['match_rate'] for k in labels]
    counts = [breakdown[k]['count'] for k in labels]

    fig = go.Figure(go.Bar(
        x=labels,
        y=rates,
        text=[f"{r:.1f}% (n={c})" for r, c in zip(rates, counts)],
        textposition='auto',
        marker_color=['#4CAF50', '#2196F3', '#FF9800'],
    ))
    fig.update_layout(
        title="Sub-Quality Detection Accuracy",
        yaxis_title="Match Rate (%)",
        yaxis_range=[0, 100],
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_company_timeline(company_df: pd.DataFrame, db_qot_df: pd.DataFrame = None):
    """Multi-axis timeline: QOT + revenue/valuation for a single company."""
    if len(company_df) == 0:
        st.info("No data for this company.")
        return

    company_df = company_df.sort_values('year')
    company_name = company_df['company_name'].iloc[0] if 'company_name' in company_df.columns else "Company"

    fig = go.Figure()

    # Calculated QOT
    fig.add_trace(go.Scatter(
        x=company_df['year'], y=company_df['calculated_qot'],
        name='Calculated QOT', mode='lines+markers',
        line=dict(color='#2196F3', width=3),
        yaxis='y1',
    ))

    # DB QOT overlay
    if db_qot_df is not None and len(db_qot_df) > 0:
        db_company = db_qot_df[db_qot_df['company_id'] == company_df['company_id'].iloc[0]]
        if len(db_company) > 0:
            db_company = db_company.sort_values('year')
            fig.add_trace(go.Scatter(
                x=db_company['year'], y=db_company['qot'],
                name='DB QOT', mode='lines+markers',
                line=dict(color='#F44336', width=2, dash='dash'),
                yaxis='y1',
            ))

    # Valuation on secondary axis
    if 'eoy_valuation' in company_df.columns:
        val = company_df['eoy_valuation'].replace(0, np.nan)
        fig.add_trace(go.Bar(
            x=company_df['year'], y=val,
            name='Valuation ($M)', opacity=0.3,
            marker_color='#4CAF50',
            yaxis='y2',
        ))

    fig.update_layout(
        title=f"{company_name} — QOT Timeline",
        xaxis_title="Year",
        yaxis=dict(title="Quality (1-5)", range=[0, 6], dtick=1),
        yaxis2=dict(title="Valuation ($M)", overlaying='y', side='right'),
        height=450,
        legend=dict(x=0, y=1.1, orientation='h'),
    )
    st.plotly_chart(fig, use_container_width=True)
