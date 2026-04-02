"""
Temporal metrics computation: queries DB, merges, computes derived metrics.
Ported from qot_calculator/calculate_metrics/calculate_metrics.py
"""
import pandas as pd
import numpy as np
from datetime import datetime
from utils.config import TIER_1_VCS, REVENUE_SOURCE_QUALITY

CURRENT_YEAR = datetime.now().year


def compute_metrics(conn, segments_df: pd.DataFrame) -> pd.DataFrame:
    """Run DB queries, merge onto segments, return enriched DataFrame."""
    base_df = segments_df[['company_id', 'company_name', 'mosaic_score', 'found_yr',
                           'year', 'segment', 'prev_segment', 'segment_changed']].copy()

    # 1. Company quality scores
    quality_df = pd.read_sql("""
        SELECT company_id, quality_score, sub_quality, market_score
        FROM companies WHERE delete = false OR delete IS NULL
    """, conn)
    base_df = base_df.merge(quality_df, on='company_id', how='left')

    # 2a. Valuations by year — uses get_company_valuation_by_year() which returns
    # market cap for public companies, deal valuations for private. Returns raw dollars.
    # Write company-year pairs to temp table, then batch-query the function.
    cy_pairs = base_df[['company_id', 'year']].drop_duplicates()
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS _cy_pairs (company_id int, year int)")
    cur.execute("DELETE FROM _cy_pairs")
    from io import StringIO
    buf = StringIO()
    cy_pairs.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_from(buf, '_cy_pairs', sep=',', columns=('company_id', 'year'))
    conn.commit()

    valuation_df = pd.read_sql("""
        SELECT cy.company_id, cy.year,
               get_company_valuation_by_year(cy.company_id, cy.year) / 1000000.0 as eoy_valuation
        FROM _cy_pairs cy
    """, conn)
    valuation_df['year'] = valuation_df['year'].astype(int)
    cur.execute("DROP TABLE IF EXISTS _cy_pairs")
    conn.commit()

    # 2b. Deal activity by year (deal_size, funding_rounds, deal_count — separate from valuation)
    deal_activity_df = pd.read_sql("""
        SELECT c.company_id,
               EXTRACT(YEAR FROM d.deal_date::date)::int as year,
               d.deal_size_in_millions as eoy_deal_size,
               d.funding_round, d.deal_id
        FROM companies c
        JOIN deals d ON c.company_id = d.funded_company_id
        WHERE (c.delete = false OR c.delete IS NULL)
          AND d.deal_date IS NOT NULL
          AND d.deal_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    """, conn)
    deal_activity_df['year'] = deal_activity_df['year'].astype(int)

    if len(deal_activity_df) > 0:
        deal_agg = deal_activity_df.groupby(['company_id', 'year']).agg(
            eoy_deal_size=('eoy_deal_size', 'max'),
            funding_rounds=('funding_round', lambda x: ', '.join(sorted(set(str(r) for r in x if pd.notna(r))))),
            deals_count=('deal_id', 'count'),
        ).reset_index()
    else:
        deal_agg = pd.DataFrame(columns=['company_id', 'year', 'eoy_deal_size',
                                          'funding_rounds', 'deals_count'])

    # Merge valuations and deal activity into val_agg for compatibility
    val_agg = valuation_df[['company_id', 'year', 'eoy_valuation']].merge(
        deal_agg, on=['company_id', 'year'], how='outer'
    )

    # 3. Revenue by year
    revenue_df = pd.read_sql("""
        SELECT DISTINCT ON (rc.company_id, rc.year)
            rc.company_id, rc.year::int as year,
            rc.value as revenue, r.source as revenue_source
        FROM revenue_cache rc
        JOIN revenue r ON rc.revenue_id = r.id
        WHERE rc.value IS NOT NULL AND rc.value > 0
        ORDER BY rc.company_id, rc.year,
            CASE r.source
                WHEN 'user' THEN 1 WHEN 'Polygon' THEN 2
                WHEN 'CB Insights' THEN 3 ELSE 4
            END
    """, conn)
    revenue_df['year'] = revenue_df['year'].astype(int)

    # 4. All deals by year
    all_deals_df = pd.read_sql("""
        SELECT c.company_id,
               EXTRACT(YEAR FROM d.deal_date::date)::int as year,
               COUNT(DISTINCT d.deal_id) as total_deals_count,
               STRING_AGG(DISTINCT d.funding_round, ', ') as all_funding_rounds
        FROM companies c
        JOIN deals d ON c.company_id = d.funded_company_id
        WHERE (c.delete = false OR c.delete IS NULL)
          AND d.deal_date IS NOT NULL
          AND d.deal_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        GROUP BY c.company_id, EXTRACT(YEAR FROM d.deal_date::date)
    """, conn)
    all_deals_df['year'] = all_deals_df['year'].astype(int)

    # 5. Exit events
    exit_df = pd.read_sql("""
        SELECT funded_company_id as company_id,
               EXTRACT(YEAR FROM deal_date::date)::int as year,
               funding_round as exit_type,
               valuation_in_millions as exit_value,
               deal_size_in_millions as exit_size
        FROM deals
        WHERE funding_round IN ('IPO', 'IPO - II', 'Acquired', 'Acq - P2P', 'Acq - Pending', 'Merger')
          AND deal_date IS NOT NULL
          AND deal_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    """, conn)
    exit_df['year'] = exit_df['year'].astype(int)
    # Keep first exit per company-year
    exit_df = exit_df.drop_duplicates(subset=['company_id', 'year'], keep='first')

    # 6. Investors by year
    investor_df = pd.read_sql("""
        SELECT DISTINCT
            d.funded_company_id as company_id,
            EXTRACT(YEAR FROM d.deal_date::date)::int as year,
            dl.investor_name
        FROM deals d
        JOIN deal_link dl ON d.deal_id = dl.deal_id
        WHERE dl.investor_name IS NOT NULL
          AND d.deal_date IS NOT NULL
          AND d.deal_date::text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    """, conn)
    investor_df['year'] = investor_df['year'].astype(int)

    # Tier 1 VC aggregation
    investor_df['is_tier1'] = investor_df['investor_name'].isin(TIER_1_VCS)
    tier1_agg = investor_df[investor_df['is_tier1']].groupby(['company_id', 'year']).agg(
        tier1_investor_count=('investor_name', 'count'),
    ).reset_index()
    tier1_agg['has_tier1_vc'] = True

    # Investor count per company-year
    inv_count = investor_df.groupby(['company_id', 'year']).agg(
        investor_count=('investor_name', 'nunique'),
    ).reset_index()

    # --- Merge all onto base ---
    result = base_df.copy()
    result = result.merge(val_agg, on=['company_id', 'year'], how='left')
    result = result.sort_values(['company_id', 'year'])

    # Forward-fill valuations within each company
    result['eoy_valuation'] = result.groupby('company_id')['eoy_valuation'].ffill()
    result['eoy_deal_size'] = result.groupby('company_id')['eoy_deal_size'].ffill()
    result['funding_rounds'] = result['funding_rounds'].fillna('')
    result['deals_count'] = result['deals_count'].fillna(0).astype(int)

    result = result.merge(revenue_df, on=['company_id', 'year'], how='left')
    result = result.merge(all_deals_df, on=['company_id', 'year'], how='left')
    result = result.merge(exit_df, on=['company_id', 'year'], how='left')
    result = result.merge(tier1_agg, on=['company_id', 'year'], how='left')
    result = result.merge(inv_count, on=['company_id', 'year'], how='left')

    # Fill defaults
    for col, default in [('eoy_valuation', 0), ('eoy_deal_size', 0), ('deals_count', 0),
                          ('revenue', 0), ('tier1_investor_count', 0), ('has_tier1_vc', False),
                          ('total_deals_count', 0), ('investor_count', 0)]:
        result[col] = result[col].fillna(default)

    # Derived flags
    result['is_unicorn'] = result['eoy_valuation'] >= 1000
    result['is_decacorn'] = result['eoy_valuation'] >= 10000

    # Company age
    def safe_founding_year(fy):
        try:
            if pd.isna(fy):
                return None
            v = int(fy)
            return v if 1800 <= v <= 2030 else None
        except (ValueError, TypeError):
            return None

    result['found_yr_clean'] = result['found_yr'].apply(safe_founding_year)
    result['company_age'] = result['year'] - result['found_yr_clean']

    # Revenue source quality
    result['revenue_source_quality'] = result['revenue_source'].map(REVENUE_SOURCE_QUALITY).fillna(0.1)

    # Enhanced: cumulative raised, peak valuation to date
    result = result.sort_values(['company_id', 'year'])
    result['cumulative_raised'] = result.groupby('company_id')['eoy_deal_size'].cumsum()
    result['peak_valuation_to_date'] = result.groupby('company_id')['eoy_valuation'].cummax()

    # Years since last deal
    result['had_deal'] = result['deals_count'] > 0
    result['last_deal_year'] = result.apply(
        lambda r: r['year'] if r['had_deal'] else np.nan, axis=1
    )
    result['last_deal_year'] = result.groupby('company_id')['last_deal_year'].ffill()
    result['years_since_last_deal'] = result['year'] - result['last_deal_year']
    result['years_since_last_deal'] = result['years_since_last_deal'].fillna(99).astype(int)
    result.drop(columns=['had_deal', 'last_deal_year'], inplace=True)

    # Years since exit
    exit_years = exit_df.groupby('company_id')['year'].min().reset_index()
    exit_years.columns = ['company_id', 'first_exit_year']
    result = result.merge(exit_years, on='company_id', how='left')
    result['years_since_exit'] = np.where(
        result['first_exit_year'].notna() & (result['year'] >= result['first_exit_year']),
        result['year'] - result['first_exit_year'],
        np.nan,
    )
    result.drop(columns=['first_exit_year'], inplace=True)

    return result


def compute_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute trajectory metrics vectorized: growth rates and stagnation counters."""
    df = df.sort_values(['company_id', 'year']).copy()

    # 3-year growth rates via shift
    g = df.groupby('company_id')

    val_3y_ago = g['eoy_valuation'].shift(3)
    df['val_growth_3y'] = (df['eoy_valuation'] - val_3y_ago) / val_3y_ago.clip(lower=1)
    df['val_growth_3y'] = df['val_growth_3y'].fillna(0)

    rev_1y_ago = g['revenue'].shift(1)
    df['rev_growth_1y'] = (df['revenue'] - rev_1y_ago) / rev_1y_ago.clip(lower=1)
    df['rev_growth_1y'] = df['rev_growth_1y'].fillna(0)

    rev_3y_ago = g['revenue'].shift(3)
    df['rev_growth_3y'] = (df['revenue'] - rev_3y_ago) / rev_3y_ago.clip(lower=1)
    df['rev_growth_3y'] = df['rev_growth_3y'].fillna(0)

    deals_3y_ago = g['deals_count'].shift(3)
    df['deal_trend_3y'] = (df['deals_count'] - deals_3y_ago) / deals_3y_ago.clip(lower=1)
    df['deal_trend_3y'] = df['deal_trend_3y'].fillna(0)

    # Long-term growth: current vs first non-zero value per company
    def long_growth(series):
        first_nonzero = series.where(series > 0).first_valid_index()
        if first_nonzero is None:
            return pd.Series(0.0, index=series.index)
        first_val = series.loc[first_nonzero]
        return (series - first_val) / max(first_val, 1)

    df['val_growth_long'] = g['eoy_valuation'].transform(long_growth)
    df['rev_growth_long'] = g['revenue'].transform(long_growth)

    # Stagnation counters: consecutive years with <5% growth
    def stagnation_counter(series):
        yoy = series.pct_change()
        stagnant = (yoy < 0.05) | yoy.isna()
        # Build consecutive counter that resets on non-stagnant
        counter = []
        c = 0
        for s in stagnant:
            if s:
                c += 1
            else:
                c = 0
            counter.append(c)
        return pd.Series(counter, index=series.index)

    df['val_stagnation_years'] = g['eoy_valuation'].transform(stagnation_counter).astype(int)
    df['rev_stagnation_years'] = g['revenue'].transform(stagnation_counter).astype(int)

    return df
