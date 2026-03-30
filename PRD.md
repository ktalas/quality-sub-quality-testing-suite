# QOT Testing Suite — Product Requirements Document

## Overview

A configurable Streamlit application for experimenting with Quality Over Time (QOT) scoring rules. Users can tune any combination of parameters, re-run the scoring algorithm, and instantly see how outputs change — both in terms of distribution and match rate against the production database.

The primary goal is to close the remaining ~18% gap between calculated QOT and the production `qot` table, while providing a repeatable, visual environment for rule experimentation.

---

## Background

The current simplified-baseline algorithm (`qot_calculator_2`) achieves ~82% match with the production database by stretching each company's current quality score backwards in time. The remaining 18% likely involves combinations of:
- Revenue and valuation trajectory signals
- Unicorn/decacorn status
- Segment-specific growth thresholds
- Mosaic score calibration

Rather than testing rules one at a time in scripts, this app provides a live feedback loop.

---

## Data Pipeline

The app builds its own `temporal_metrics.parquet` by querying the production PostgreSQL database directly. A "Refresh Data" button in the sidebar triggers the full pipeline: segmentation → metrics calculation → parquet write. Parquet format is used for faster read performance (~5x vs CSV).

Data is stored in: `data/temporal_metrics.parquet`

### Available Data Variables

#### Core Metrics (from DB)

| Variable | Type | Source | Description |
|---|---|---|---|
| `company_id` | int | companies | Primary key |
| `company_name` | string | companies | Company name |
| `quality_score` | int (1–5) | companies | Current quality assigned by analysts |
| `sub_quality` | string | companies | Hot, Iconic, Legacy, Incumbent |
| `mosaic_score` | float | companies | Composite signal score |
| `segment` | string | segmentation query | VC, Growth, Public, PE, Acquired, Other, Uncategorized |
| `year` | int | deals (extracted) | Calendar year for this record |
| `eoy_valuation` | float (millions) | deals | End-of-year valuation (max per year, forward-filled) |
| `eoy_deal_size` | float (millions) | deals | Deal size at end of year |
| `deals_count` | int | deals | Number of deals that year |
| `funding_rounds` | string | deals | Funding round types that year (comma-separated) |
| `total_deals_count` | int | deals | Count of all deals that year |
| `all_funding_rounds` | string | deals | All funding round types that year |
| `revenue` | float (USD) | revenue_cache/revenue | Annual revenue (prioritized: user > Polygon > CB Insights) |
| `revenue_source` | string | revenue | Source of revenue data (for confidence weighting) |
| `has_tier1_vc` | bool | deal_link | Backed by Tier 1 VC |
| `tier1_investor_count` | int | deal_link | Number of Tier 1 investors |
| `is_unicorn` | bool | derived | Valuation ≥ $1B |
| `is_decacorn` | bool | derived | Valuation ≥ $10B |
| `exit_type` | string | deals | IPO, IPO - II, Acquired, Acq - P2P, Merger, etc. |
| `exit_value` | float (millions) | deals | Exit transaction valuation |
| `exit_size` | float (millions) | deals | Exit deal size |
| `exit_date` | date | deals | Date of exit event |
| `company_age` | int | derived | Years since founding |
| `found_yr` | int | companies | Year founded |

#### Enhanced Metrics (new additions beyond original pipeline)

| Variable | Type | Source | Description |
|---|---|---|---|
| `cumulative_raised` | float (millions) | deals | Running total of capital raised to date |
| `peak_valuation_to_date` | float (millions) | deals | Highest valuation achieved up to this year |
| `years_since_last_deal` | int | deals | Years since most recent deal activity |
| `investor_count` | int | deal_link | Total unique investors this year |
| `avg_investors_per_deal` | float | deal_link | Average investors per deal this year |
| `primary_investor_tier` | string | deal_link/vc_tiers | Best investor tier in round (tier_1/2/3/4) |
| `funding_round_quality` | float | deals | Quality-weighted funding round score |
| `stage_bucket` | string | derived | Inferred stage: early, mid, growth, late |
| `deal_group` | string | deals | Classified deal type: IPO, VC, VC_FU, PE, MA, DEBT, etc. |
| `revenue_source_quality` | float | derived | Confidence weight of revenue source (0–1) |
| `headcount` | int | companies (if available) | Most recent known headcount |
| `years_since_exit` | int | derived | Years since exit event (null if no exit) |
| `prev_segment` | string | segmentation | Segment in prior year (for transition detection) |
| `segment_changed` | bool | derived | Whether segment changed from prior year |

#### Derived Trajectory Variables (computed at data-build time, not runtime)

| Variable | Type | Description |
|---|---|---|
| `val_growth_3y` | float | 3-year valuation growth rate |
| `val_growth_long` | float | Total valuation growth from first data point |
| `val_stagnation_years` | int | Consecutive years of <5% valuation growth |
| `rev_growth_3y` | float | 3-year revenue growth rate |
| `rev_growth_long` | float | Total revenue growth from first data point |
| `rev_stagnation_years` | int | Consecutive years of <5% revenue growth |
| `deal_trend_3y` | float | 3-year deal activity trend |

---

## Parameter Categories

### 1. Base Quality Assignment
Controls how the current quality score is stretched across historical years.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `upgrade_hot_to_5` | bool | true | Promote Hot sub_quality to Q5 |
| `upgrade_iconic_to_5` | bool | true | Promote Iconic sub_quality to Q5 |
| `mosaic_900_floor` | int (1–5) | 4 | Floor quality for mosaic ≥ 900 |
| `mosaic_750_floor` | int (1–5) | 3 | Floor quality for mosaic ≥ 750 |
| `mosaic_650_floor` | int (1–5) | 2 | Floor quality for mosaic ≥ 650 |
| `mosaic_900_threshold` | float | 900 | Mosaic score cutoff for top upgrade |
| `mosaic_750_threshold` | float | 750 | Mosaic score cutoff for mid upgrade |
| `mosaic_650_threshold` | float | 650 | Mosaic score cutoff for low upgrade |

### 2. Upgrade Rules (Revenue-based)
Controls which revenue signals trigger quality upgrades.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_revenue_upgrade` | bool | false | Enable revenue-based upgrades |
| `rev_upgrade_min_revenue` | float (USD) | 1,000,000,000 | Minimum revenue to qualify |
| `rev_upgrade_growth_threshold` | float | 0.30 | Minimum 3yr revenue growth rate |
| `rev_upgrade_target_quality` | int (1–5) | 5 | Quality to upgrade to |
| `public_rev_upgrade_enabled` | bool | false | Apply separate rule for public companies |
| `public_rev_upgrade_min_revenue` | float (USD) | 5,000,000,000 | Public min revenue threshold |
| `public_rev_upgrade_growth_threshold` | float | 0.20 | Public revenue growth threshold |

### 3. Upgrade Rules (Valuation-based)
Controls which valuation signals trigger quality upgrades.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_unicorn_upgrade` | bool | false | Unicorn status as upgrade signal |
| `unicorn_upgrade_quality_floor` | int (1–5) | 4 | Quality floor for unicorns |
| `enable_decacorn_upgrade` | bool | false | Decacorn status as upgrade signal |
| `decacorn_upgrade_quality_floor` | int (1–5) | 5 | Quality floor for decacorns |
| `enable_val_growth_upgrade` | bool | false | Valuation growth rate upgrade |
| `val_growth_threshold` | float | 2.0 | 3yr valuation growth rate to qualify |
| `val_growth_upgrade_target` | int (1–5) | 5 | Quality to upgrade to |
| `require_revenue_validation` | bool | false | Require minimum revenue alongside valuation rules |
| `val_upgrade_min_revenue` | float (USD) | 500,000,000 | Revenue floor when validation required |

### 4. Downgrade Rules
Controls which signals trigger quality reductions.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_revenue_decline_downgrade` | bool | false | Downgrade on revenue decline |
| `rev_decline_threshold` | float | -0.20 | 3yr revenue decline rate to trigger downgrade |
| `rev_decline_segments` | list | [Public] | Which segments this rule applies to |
| `enable_stagnation_downgrade` | bool | false | Downgrade on multi-year stagnation |
| `rev_stagnation_years_threshold` | int | 5 | Years of stagnation before downgrade |
| `val_stagnation_years_threshold` | int | 5 | Years of valuation stagnation (VC) |
| `stagnation_downgrade_amount` | int | 1 | How many quality levels to drop |

### 5. Segment Rules
Controls segment-specific logic.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_public_to_pe_downgrade` | bool | true | Downgrade quality on Public→PE transition |
| `public_to_pe_min_quality` | int | 4 | Minimum quality to trigger this rule |
| `public_to_pe_downgrade_amount` | int | 1 | How many levels to drop |
| `enable_pe_deal_decline_downgrade` | bool | false | Downgrade PE cos with declining deal activity |
| `pe_deal_decline_threshold` | float | -0.50 | 3yr deal activity decline to trigger |
| `enable_taken_private_cap` | bool | false | Cap quality at Q3 for companies taken private |

### 6. Acquisition Rules

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_acquisition_degradation` | bool | true | Q5 acquired companies drop to Q4 |
| `acquisition_degradation_delay` | int | 2 | Years after acquisition before degradation |
| `acquisition_degradation_target` | int | 4 | Quality to degrade to |

### 7. Tier 1 VC Rules

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_tier1_vc_upgrade` | bool | false | Tier 1 VC as upgrade signal |
| `tier1_vc_min_valuation` | float (USD) | 500,000,000 | Minimum valuation to qualify |
| `tier1_vc_growth_threshold` | float | 0.50 | Valuation growth threshold |
| `tier1_vc_upgrade_target` | int | 5 | Quality to upgrade to |

### 8. Advanced Rules
Rules ported from `assign_quality.py` that cover edge cases and segment-specific logic.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `enable_exceptional_val_growth` | bool | true | 200%+ 3yr valuation growth → Q5 (non-PE only) |
| `exceptional_val_growth_threshold` | float | 2.0 | 3yr valuation growth rate for exceptional upgrade |
| `enable_pe_hot_rules` | bool | true | PE-specific Q5 rules (high-revenue PE companies) |
| `pe_hot_rev_threshold_high` | float (USD) | 50,000,000,000 | PE revenue threshold (lower growth req) |
| `pe_hot_growth_threshold_high` | float | 0.50 | Revenue growth rate for high-rev PE |
| `pe_hot_rev_threshold_low` | float (USD) | 20,000,000,000 | PE revenue threshold (higher growth req) |
| `pe_hot_growth_threshold_low` | float | 0.75 | Revenue growth rate for low-rev PE |
| `enable_rev_growth_upgrade` | bool | true | Exceptional revenue growth → Q5 |
| `rev_growth_upgrade_min_revenue` | float (USD) | 100,000,000 | Revenue floor for growth upgrade |
| `rev_growth_upgrade_threshold` | float | 1.50 | 3yr revenue growth rate threshold |
| `enable_legacy_exclusion` | bool | true | Legacy sub_quality companies cannot be Q5 |
| `enable_legacy_penalty` | bool | false | Cap quality for legacy companies |
| `legacy_penalty_max_quality` | int (1–5) | 3 | Max quality for legacy companies |
| `enable_val_decline_downgrade` | bool | true | Downgrade on valuation decline (VC segment) |
| `val_decline_threshold` | float | -0.30 | 3yr valuation decline rate to trigger |
| `enable_growth_rev_stagnation` | bool | true | Growth segment: revenue stagnation downgrade |
| `growth_rev_stagnation_years` | int | 3 | Years of stagnation before downgrade (Growth) |
| `enable_stagnant_val_rev_check` | bool | true | For stagnant valuations, require exceptional revenue growth |
| `stagnant_val_threshold` | float | 0.10 | Valuation growth below this = stagnant |
| `enable_no_recent_funding_check` | bool | true | Higher revenue bar for companies with no deals since 2022 |

---

## Core Features

### Parameter Panel
- Organized into tabs matching the 8 categories above
- Toggle each rule category on/off independently
- Numeric sliders and inputs with sensible min/max bounds
- Live indication of which rules are enabled

### Data Management
- **Refresh Data** button in sidebar triggers full pipeline: DB query → segmentation → metrics calculation → parquet write
- Data stored as `data/temporal_metrics.parquet` for fast loading
- Progress indicator during refresh (~15–30 seconds)
- Parquet file is cached locally; only regenerated on explicit refresh

### Scoring Engine
- Loads `data/temporal_metrics.parquet` (pre-built from DB)
- Applies all active rules in a deterministic order:
  1. Base quality stretch
  2. Sub-quality upgrades (Hot/Iconic)
  3. Mosaic upgrades
  4. Revenue upgrades
  5. Valuation upgrades
  6. Tier 1 VC upgrades
  7. Advanced rules (exceptional growth, PE-specific, legacy, stagnant-val checks)
  8. Downgrade rules (revenue decline, stagnation, valuation decline)
  9. Segment transition rules
  10. Acquisition degradation
- Applies existing `spread_quality` logic as the default temporal spreading step
- Outputs a `qot` value (1–5) for each company-year record

### DB Match Rate Panel
The primary success metric. Compares against **two** production sources:

**1. QOT Table Match** (`qot` table: `company_id`, `year`, `qot`):
- **Overall match rate** — % of company-year records matching
- **Match rate by segment** — breakdown across VC, Growth, Public, PE, Acquired, Other
- **Match rate by quality level** — how well each Q1–Q5 band is reproduced
- **Delta from baseline** — change vs. the 82.25% simplified-baseline

**2. Companies Table Match** (`companies` table: `quality`, `sub_quality`):
- **Quality match rate** — calculated quality tier vs `companies.quality` (Low, Medium, High, Top)
- **Sub-quality match rate** — Hot/Iconic/Legacy classification accuracy
- Note: `companies.quality` maps to the *current* quality, not temporal; useful for validating the most recent year
- Context: Iconic = companies that achieved Q5/Hot status at some point in their history; they may or may not still be highest quality

### Company Lookup
- Search by company name or ID in the sidebar
- Shows: company metadata, full QOT trajectory, all rule impacts on that company
- Useful for debugging specific mismatches against production

### Diff Explorer
Drill into the records that changed from the baseline:
- Table of mismatches: company name, segment, year, calculated QOT, DB QOT, difference direction (upgraded/downgraded)
- Filter by: segment, quality tier, which rule caused the change
- Sortable by rule impact count

### Visualizations
- **QOT Distribution** — histogram of Q1–Q5 counts for calculated vs DB
- **Match Rate by Year** — line chart showing match rate per year
- **Rule Impact** — bar chart showing how many records each enabled rule touched
- **Company-Level Timeline** — select a specific company to see its QOT year-by-year alongside revenue, valuation, and the DB value

### Config Management
- Export current parameter config as JSON or YAML
- Import a saved config to restore a prior run
- Reset to simplified-baseline defaults
- Save named "experiments" for comparison

---

## Technology Stack

| Component | Choice |
|---|---|
| UI Framework | Streamlit |
| Data Processing | Pandas, NumPy |
| Data Storage | Parquet (via PyArrow) |
| Visualization | Plotly |
| Database | PostgreSQL via psycopg2 |
| Config | JSON/YAML |
| Environment | python-dotenv |
| Deployment | Local only (V1) |

Directory structure:
```
qot_testing_suite/
├── app.py                    # Main Streamlit entry point
├── requirements.txt
├── .env                      # DB credentials (not committed)
├── data/                     # Generated data (not committed)
│   └── temporal_metrics.parquet
├── components/
│   ├── parameter_inputs.py   # All 8 parameter tabs and widgets
│   ├── visualizations.py     # Plotly charts
│   ├── diff_table.py         # Mismatch explorer table
│   └── validation.py         # Parameter constraint checks
├── engine/
│   ├── scoring.py            # Core QOT rule engine
│   ├── rules.py              # Each rule as an isolated function
│   ├── spread.py             # Spread quality temporal logic (default from existing pipeline)
│   └── compare.py            # DB match rate calculation (qot table + companies table)
├── pipeline/
│   ├── build_metrics.py      # Orchestrates DB → parquet pipeline
│   ├── segmentation.py       # Company segmentation (ported from qot_calculator)
│   └── metrics.py            # Temporal metrics computation (ported from qot_calculator)
└── utils/
    ├── data_loader.py        # Load parquet + production comparison data from DB
    ├── config.py             # Config serialization/defaults
    └── caching.py            # Streamlit cache wrappers
```

---

## Performance Requirements

- Data refresh (DB → parquet): < 60 seconds
- Parquet load: < 2 seconds
- Scoring run (all rules): < 10 seconds for full dataset
- DB comparison query: < 5 seconds
- Total interactive cycle (score + compare): < 15 seconds

---

## Success Criteria

1. All 8 rule categories are toggleable independently
2. A full scoring run completes in under 15 seconds for the full dataset
3. Match rate vs both `qot` table and `companies.quality`/`sub_quality` displayed after every run
4. Any individual company's QOT trajectory is inspectable
5. Configs can be exported and re-imported reproducibly
6. Data can be refreshed from the production DB via a single button click

---

## V2 — Future Enhancements

The following features are deferred to V2:

### Configurable Spread Quality
The `spread_quality.py` step (temporal spreading with progress multipliers, exit year boosts, post-exit handling) currently runs with fixed defaults from the existing pipeline. In V2, expose spread parameters in the UI:
- Progress multiplier thresholds (valuation and revenue milestones)
- Exit year boost values by exit size
- Post-exit quality maintenance multipliers
- Decay floors and grace periods

### Comparison Mode
Run two configs side by side:
- Match rate for Config A vs Config B
- Records that Config A gets right but B gets wrong (and vice versa)
- Net improvement/regression table

### External Deployment
Deploy to AWS App Runner (following the strength2 testing suite pattern):
- Dockerfile and deploy.sh
- VPC connector for RDS access
- Multi-user session management
- Authentication

### Additional Signals
Potential additional metrics to incorporate:
- CB Insights Mosaic sub-components (momentum, market, money, management)
- Headcount growth trends
- Funding round quality scoring (from claude_charlie model)
- Momentum smoothing with grace periods (from claude_delta model)
- Revenue efficiency (revenue per dollar raised)
