"""
Company segmentation: classifies companies into segments per year.
Ported from qot_calculator/company_segmentation/segment_companies_temporal.py
"""
import pandas as pd
from datetime import datetime

CURRENT_YEAR = datetime.now().year


def run_segmentation(conn) -> pd.DataFrame:
    """Run the temporal segmentation SQL and add transition columns.
    Returns DataFrame with: company_id, company_name, mosaic_score, found_yr, year, segment,
                            prev_segment, segment_changed
    """
    sql = f"""
    WITH company_deals_aggregated AS (
        SELECT
            c.company_id,
            c.company_name,
            c.mosaic_score,
            c.found_yr,
            c.stock_symbol,
            CASE
                WHEN d.deal_date IS NOT NULL
                     AND d.deal_date::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'
                THEN EXTRACT(YEAR FROM d.deal_date)
                ELSE NULL
            END as deal_year,
            COUNT(DISTINCT CASE WHEN d.funding_round_category = 'IPO' THEN d.deal_id END) as ipo_count,
            COUNT(DISTINCT CASE
                WHEN d.funding_round IN (
                    'Angel', 'Pre-Seed', 'Seed', 'Series A', 'Series B', 'Series C', 'Series D',
                    'Angel - II', 'Angel - III', 'Pre-Seed - II', 'Seed - II',
                    'Seed - III', 'Seed VC', 'Series A - II', 'Series B - II',
                    'Unattributed VC'
                ) THEN d.deal_id
            END) as early_vc_count,
            COUNT(DISTINCT CASE
                WHEN d.funding_round IN (
                    'Series E', 'Series F', 'Series G', 'Series H', 'Series I', 'Series J', 'Series K'
                ) THEN d.deal_id
            END) as growth_vc_count,
            COUNT(DISTINCT CASE
                WHEN d.funding_round IN ('Growth Equity', 'Growth Equity - II', 'Growth Equity - III')
                THEN d.deal_id
            END) as growth_equity_count,
            COUNT(DISTINCT CASE
                WHEN d.funding_round IN (
                    'Private Equity', 'Private Equity - II', 'Private Equity - III',
                    'Leveraged Buyout', 'Management Buyout'
                ) THEN d.deal_id
            END) as pe_count,
            BOOL_OR(d.valuation_in_millions IS NOT NULL AND d.valuation_in_millions >= 1000) as has_billion_plus_valuation,
            BOOL_OR(d.valuation_in_millions IS NOT NULL AND d.valuation_in_millions >= 10000) as has_decacorn_valuation,
            BOOL_OR(d.funding_round IN ('Acquired', 'Acq - P2P', 'Acq - Pending', 'Merger')) as has_acquisition,
            BOOL_OR(d.funding_round IN ('Acq - Fin', 'Corporate Majority', 'Take Private', 'Take Private - II')) as has_pe_acquisition,
            BOOL_OR(d.funding_round IN ('PIPE', 'PIPE - II', 'PIPE - III', 'PIPE - IV', 'PIPE - V', 'PIPE - VI', 'PIPE - VII')) as has_pipe_round,
            BOOL_OR(d.funding_round IN ('Management Buyout', 'Reverse Merger', 'Corporate Majority - P2P', 'Corporate Majority - P2P - II')) as has_ownership_restructuring,
            COUNT(DISTINCT d.deal_id) as total_deals
        FROM companies c
        LEFT JOIN deals d ON c.company_id = d.funded_company_id
        WHERE (c.delete = false OR c.delete IS NULL OR c.delete = 'false')
        GROUP BY c.company_id, c.company_name, c.mosaic_score, c.found_yr, c.stock_symbol, deal_year
    ),
    company_deals_cumulative AS (
        SELECT
            company_id, company_name, mosaic_score, found_yr, stock_symbol, deal_year,
            SUM(ipo_count) OVER w as ipo_count_cumulative,
            SUM(early_vc_count) OVER w as early_vc_count_cumulative,
            SUM(growth_vc_count) OVER w as growth_vc_count_cumulative,
            SUM(growth_equity_count) OVER w as growth_equity_count_cumulative,
            SUM(pe_count) OVER w as pe_count_cumulative,
            SUM(total_deals) OVER w as total_deals_cumulative,
            BOOL_OR(has_billion_plus_valuation) OVER w as has_billion_plus_valuation_cumulative,
            BOOL_OR(has_decacorn_valuation) OVER w as has_decacorn_valuation_cumulative,
            BOOL_OR(has_acquisition) OVER w as has_acquisition_cumulative,
            BOOL_OR(has_pe_acquisition) OVER w as has_pe_acquisition_cumulative,
            BOOL_OR(has_pipe_round) OVER w as has_pipe_round_cumulative,
            BOOL_OR(has_ownership_restructuring) OVER w as has_ownership_restructuring_cumulative
        FROM company_deals_aggregated
        WHERE deal_year IS NOT NULL
        WINDOW w AS (PARTITION BY company_id ORDER BY deal_year ROWS UNBOUNDED PRECEDING)
    ),
    company_years AS (
        SELECT DISTINCT
            c.company_id, c.company_name, c.mosaic_score, c.found_yr, c.stock_symbol,
            c.ipo_date, c.ipo_yr,
            generate_series(
                GREATEST(COALESCE(c.found_yr::integer, {CURRENT_YEAR} - 30), {CURRENT_YEAR} - 30),
                {CURRENT_YEAR}
            ) as year
        FROM companies c
        WHERE (c.delete = false OR c.delete IS NULL OR c.delete = 'false')
    ),
    company_timeline AS (
        SELECT
            cy.company_id, cy.company_name, cy.mosaic_score, cy.found_yr, cy.stock_symbol, cy.year,
            GREATEST(
                COALESCE(FIRST_VALUE(cd.ipo_count_cumulative) OVER w, 0),
                CASE WHEN cy.ipo_yr IS NOT NULL AND cy.ipo_yr ~ '^[0-9]{{4}}$' AND cy.year >= cy.ipo_yr::integer THEN 1 ELSE 0 END
            ) as ipo_count,
            COALESCE(FIRST_VALUE(cd.early_vc_count_cumulative) OVER w, 0) as early_vc_count,
            COALESCE(FIRST_VALUE(cd.growth_vc_count_cumulative) OVER w, 0) as growth_vc_count,
            COALESCE(FIRST_VALUE(cd.growth_equity_count_cumulative) OVER w, 0) as growth_equity_count,
            COALESCE(FIRST_VALUE(cd.pe_count_cumulative) OVER w, 0) as pe_count,
            COALESCE(FIRST_VALUE(cd.has_billion_plus_valuation_cumulative) OVER w, false) as has_billion_plus_valuation,
            COALESCE(FIRST_VALUE(cd.has_decacorn_valuation_cumulative) OVER w, false) as has_decacorn_valuation,
            COALESCE(FIRST_VALUE(cd.total_deals_cumulative) OVER w, 0) as total_deals,
            COALESCE(FIRST_VALUE(cd.has_acquisition_cumulative) OVER w, false) as has_acquisition,
            COALESCE(FIRST_VALUE(cd.has_pe_acquisition_cumulative) OVER w, false) as has_pe_acquisition,
            COALESCE(FIRST_VALUE(cd.has_pipe_round_cumulative) OVER w, false) as has_pipe_round,
            COALESCE(FIRST_VALUE(cd.has_ownership_restructuring_cumulative) OVER w, false) as has_ownership_restructuring,
            (GREATEST(
                COALESCE(FIRST_VALUE(cd.ipo_count_cumulative) OVER w, 0),
                CASE WHEN cy.ipo_yr IS NOT NULL AND cy.ipo_yr ~ '^[0-9]{{4}}$' AND cy.year >= cy.ipo_yr::integer THEN 1 ELSE 0 END
            ) > 0) OR (cy.ipo_yr IS NOT NULL AND cy.ipo_yr ~ '^[0-9]{{4}}$' AND cy.year >= cy.ipo_yr::integer) as has_public_status
        FROM company_years cy
        LEFT JOIN company_deals_cumulative cd ON cy.company_id = cd.company_id AND cd.deal_year <= cy.year
        WINDOW w AS (PARTITION BY cy.company_id, cy.year ORDER BY cd.deal_year DESC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
    )
    SELECT DISTINCT ON (company_id, year)
        company_id, company_name, mosaic_score, found_yr, year,
        CASE
            WHEN has_acquisition THEN 'Acquired'
            WHEN (pe_count > 0 AND pe_count >= (early_vc_count + growth_vc_count)) OR has_pe_acquisition THEN 'PE'
            WHEN has_public_status AND NOT (has_pe_acquisition OR has_ownership_restructuring) THEN 'Public'
            WHEN (early_vc_count > 0 AND (growth_vc_count > 0 OR growth_equity_count > 0) AND has_billion_plus_valuation)
                 OR (early_vc_count > 0 AND has_decacorn_valuation) THEN 'Growth'
            WHEN early_vc_count > 0 THEN 'VC'
            WHEN total_deals > 0 THEN 'Other'
            ELSE 'Uncategorized'
        END as segment
    FROM company_timeline
    ORDER BY company_id, year;
    """

    df = pd.read_sql(sql, conn)
    df['year'] = df['year'].astype(int)

    # Add transition columns
    df = df.sort_values(['company_id', 'year'])
    df['prev_segment'] = df.groupby('company_id')['segment'].shift(1)
    df['segment_changed'] = (df['segment'] != df['prev_segment']) & df['prev_segment'].notna()

    return df
