"""
Streamlit cache wrappers for DB connections and data loading.
"""
import os
import streamlit as st
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv()


@st.cache_resource
def get_cached_connection():
    """Cached DB connection (not serializable — use cache_resource)."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        st.error("DATABASE_URL environment variable not set. Check your .env file.")
        return None
    return psycopg2.connect(database_url)


@st.cache_data(ttl=3600)
def load_temporal_metrics() -> pd.DataFrame:
    """Load temporal metrics from parquet. 1-hour TTL cache."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "temporal_metrics.parquet")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


@st.cache_data(ttl=3600)
def load_production_qot(_conn) -> pd.DataFrame:
    """Load production qot table for comparison."""
    sql = "SELECT company_id, year, qot FROM qot"
    return pd.read_sql(sql, _conn)


@st.cache_data(ttl=3600)
def load_production_companies(_conn) -> pd.DataFrame:
    """Load companies table (quality, sub_quality) for comparison."""
    sql = """
    SELECT company_id, quality, sub_quality
    FROM companies
    WHERE delete = false OR delete IS NULL
    """
    return pd.read_sql(sql, _conn)
