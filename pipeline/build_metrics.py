"""
Pipeline orchestrator: DB -> segmentation -> metrics -> parquet.
"""
import os
import streamlit as st
from pipeline.segmentation import run_segmentation
from pipeline.metrics import compute_metrics, compute_derived_metrics


def build_temporal_metrics(conn):
    """Full pipeline: segmentation -> metrics -> derived -> parquet.
    Returns the built DataFrame.
    """
    with st.spinner("Step 1/3: Segmenting companies..."):
        segments = run_segmentation(conn)
        st.text(f"  Segmented {len(segments):,} company-year records")

    with st.spinner("Step 2/3: Computing metrics..."):
        metrics = compute_metrics(conn, segments)
        st.text(f"  Computed metrics for {len(metrics):,} records")

    with st.spinner("Step 3/3: Computing trajectories..."):
        df = compute_derived_metrics(metrics)
        st.text(f"  Final dataset: {len(df):,} records, {df['company_id'].nunique():,} companies")

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    data_dir = os.path.abspath(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    path = os.path.join(data_dir, "temporal_metrics.parquet")
    df.to_parquet(path, index=False)

    return df
