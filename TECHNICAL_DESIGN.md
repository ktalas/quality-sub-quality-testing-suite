# QOT Testing Suite — Technical Design Document

## 1. Context & Prior Art

### Existing Systems

**`qot_calculator/` pipeline** — The production-grade QOT calculation pipeline in `data_cleaning/` with 4 sequential steps:
1. **Company Segmentation** (`segment_companies_temporal.py`) — classifies companies into VC, Growth, Public, PE, Acquired, Other per year using a multi-CTE SQL query against `companies` + `deals`
2. **Calculate Metrics** (`calculate_metrics.py`) — generates `temporal_metrics.csv` with per-company-year financial and deal data from 7 SQL queries
3. **Assign Quality** (`assign_quality.py`) — applies rule-based logic to assign Q1–Q5 scores using mosaic, revenue, valuation, funding, and segment signals
4. **Spread Quality** (`spread_quality.py`) — creates temporal view from founding to present with progress multipliers and exit handling

**`qot_calculator_2/`** — A simplified baseline that stretches each company's current quality score backwards in time. Achieves ~82% match with the production `qot` DB table.

**Strength 2.0 Testing Suite** (`strength2/testing_suite/`) — An existing Streamlit app with the *exact same architectural pattern* we need: interactive parameter tuning → scoring engine → results visualization. This serves as our primary implementation template.

### What This App Does

Wraps the `assign_quality.py` logic in a Streamlit UI, making every threshold, toggle, and rule parameter adjustable at runtime. The app manages its own data pipeline (DB → parquet), runs parameterized scoring with the existing `spread_quality` logic as default, and compares results against both the production `qot` table and `companies.quality`/`sub_quality`.

---

## 2. Architecture

### High-Level Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Streamlit UI                                                     │
│                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐    │
│  │  Refresh     │──▶│  Parquet     │──▶│  Scoring Engine    │    │
│  │  Data (DB)   │   │  Cache       │   │  (8 rule tabs +    │    │
│  │              │   │  data/       │   │   spread_quality)  │    │
│  └─────────────┘   └──────────────┘   └────────┬───────────┘    │
│                                                  │                │
│  ┌──────────────┐   ┌──────────────┐   ┌────────▼───────────┐   │
│  │  Parameter    │──▶│  Config      │   │  Comparison        │   │
│  │  Panel        │   │  Engine      │   │  Engine             │   │
│  │  (8 tabs)     │   │              │   │                     │   │
│  └──────────────┘   └──────────────┘   └────────┬───────────┘   │
│                                                  │                │
│                                        ┌─────────▼──────────┐   │
│                                        │  Production DB     │   │
│                                        │  • qot table       │   │
│                                        │  • companies table │   │
│                                        └────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
qot_testing_suite/
├── app.py                        # Main Streamlit entry point
├── requirements.txt
├── .env                          # DB credentials (not committed)
├── .gitignore
├── PRD.md
├── TECHNICAL_DESIGN.md
├── data/                         # Generated data (gitignored)
│   └── temporal_metrics.parquet
├── pipeline/
│   ├── __init__.py
│   ├── build_metrics.py          # Orchestrator: DB → segmentation → metrics → parquet
│   ├── segmentation.py           # Company segmentation (ported from qot_calculator)
│   └── metrics.py                # Temporal metrics computation (ported from qot_calculator)
├── engine/
│   ├── __init__.py
│   ├── scoring.py                # Core QOT rule engine (orchestrator)
│   ├── rules.py                  # Each rule as an isolated, testable function
│   ├── spread.py                 # Spread quality logic (ported from existing pipeline)
│   └── compare.py                # DB match rate calculation (qot + companies tables)
├── components/
│   ├── __init__.py
│   ├── parameter_inputs.py       # 8 parameter tabs with widgets
│   ├── visualizations.py         # Plotly charts (distribution, match rate, timeline)
│   ├── diff_table.py             # Mismatch explorer with filtering
│   └── validation.py             # Parameter constraint checks
└── utils/
    ├── __init__.py
    ├── data_loader.py            # Load parquet + query production comparison data
    ├── config.py                 # Config serialization, defaults, experiments
    └── caching.py                # Streamlit cache wrappers
```

---

## 3. Data Pipeline (`pipeline/`)

The app owns its data pipeline rather than depending on externally-generated CSVs. The sidebar "Refresh Data" button triggers the full pipeline.

### 3.1 Pipeline Orchestrator (`pipeline/build_metrics.py`)

```python
def build_temporal_metrics(conn) -> pd.DataFrame:
    """Full pipeline: segmentation → metrics → derived → parquet.
    Called from sidebar 'Refresh Data' button.
    Returns the built DataFrame (also saves to data/temporal_metrics.parquet).
    """
    with st.spinner("Step 1/3: Segmenting companies..."):
        segments = run_segmentation(conn)

    with st.spinner("Step 2/3: Computing metrics..."):
        metrics = compute_metrics(conn, segments)

    with st.spinner("Step 3/3: Computing trajectories..."):
        df = compute_derived_metrics(metrics)

    os.makedirs("data", exist_ok=True)
    df.to_parquet("data/temporal_metrics.parquet", index=False)
    return df
```

### 3.2 Company Segmentation (`pipeline/segmentation.py`)

Ported from `qot_calculator/company_segmentation/segment_companies_temporal.py`. Runs the multi-CTE SQL query that:

1. Aggregates deals by year with cumulative counts per funding category
2. Generates year ranges per company (founding year → current year) via `generate_series()`
3. Classifies segment per company-year in priority order:
   - **Acquired** — has acquisition deal
   - **PE** — PE count >= early VC + growth VC counts, or PE acquisition/take-private
   - **Public** — has IPO, unless taken private
   - **Growth** — early VC + growth/late-stage + $1B+ valuation, or $10B+ valuation
   - **VC** — has early-stage VC funding
   - **Other** — has deals but doesn't fit above
   - **Uncategorized** — no deal data
4. Tracks `prev_segment` and `segment_changed` for transition detection

**Output columns:** `company_id`, `year`, `segment`, `prev_segment`, `segment_changed`

**Funding round categories used:**
```
Early VC:     Angel, Pre-Seed, Seed, Series A–D (and variants)
Growth VC:    Series E–K
Growth Equity: Growth Equity (and variants)
PE:           Private Equity, Leveraged Buyout, Management Buyout
Acquisition:  Acquired, Acq - P2P, Acq - Pending, Merger
PE Acquisition: Acq - Fin, Corporate Majority, Take Private
```

### 3.3 Metrics Computation (`pipeline/metrics.py`)

Ported and enhanced from `qot_calculator/calculate_metrics/calculate_metrics.py`. Runs 7 SQL queries against the production DB:

| Query | Tables | Key Fields |
|---|---|---|
| Company quality | `companies` | company_id, company_name, quality_score, sub_quality, mosaic_score, found_yr |
| Valuations by year | `companies` + `deals` | eoy_valuation, eoy_deal_size, deals_count, funding_rounds |
| Revenue by year | `revenue_cache` + `revenue` | revenue, revenue_source (prioritized: user > Polygon > CB Insights > others) |
| All deals by year | `companies` + `deals` | total_deals_count, all_funding_rounds |
| Exit events | `deals` | exit_type, exit_value, exit_size, exit_date |
| Investors by year | `deals` + `deal_link` | investor_name (for Tier 1 VC detection) |
| Deal details | `deals` + `deal_link` | For enhanced metrics: investor counts, deal groups |

**Enhanced metrics (new vs. existing pipeline):**

```python
def compute_enhanced_metrics(df: pd.DataFrame, conn) -> pd.DataFrame:
    """Adds metrics not in the original calculate_metrics.py:
    - cumulative_raised: running sum of deal_size_in_millions
    - peak_valuation_to_date: running max of eoy_valuation
    - years_since_last_deal: years since most recent deal
    - investor_count: unique investors per company-year
    - avg_investors_per_deal: investors / deals ratio
    - primary_investor_tier: best investor tier (tier_1/2/3/4)
    - funding_round_quality: quality-weighted funding round score
    - stage_bucket: inferred stage (early/mid/growth/late)
    - deal_group: classified deal type (IPO/VC/VC_FU/PE/MA/DEBT/etc.)
    - revenue_source_quality: confidence weight (user=1.0, polygon=1.0, cbi=0.3, etc.)
    - years_since_exit: years since exit event
    """
```

**Tier 1 VCs** (hardcoded list, same as existing pipeline):
Sequoia Capital, Andreessen Horowitz, Accel, Benchmark, Kleiner Perkins, GV, Greylock Partners, Bessemer Venture Partners, Index Ventures, Lightspeed Venture Partners, NEA, Founders Fund, General Catalyst, Tiger Global Management, Insight Partners, Battery Ventures, Redpoint Ventures, Matrix Partners, Union Square Ventures, First Round Capital, Spark Capital, Thrive Capital, Coatue Management

**Revenue source quality mapping:**
```python
REVENUE_SOURCE_QUALITY = {
    "user": 1.0,
    "Polygon": 1.0,
    "CB Insights": 0.3,
    "calculated": 0.3,
    "privco": 0.3,
    "initial": 0.2,
    "OpenAI": 0.1,
}
```

### 3.4 Derived Trajectory Metrics

Computed in Python after all DB data is assembled (these were previously recomputed every run in `assign_quality.py` — now pre-computed and stored in parquet):

```python
def compute_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Group by company_id, sort by year, compute:
    - val_growth_3y: (val_now - val_3y_ago) / max(val_3y_ago, 1)
    - val_growth_long: (val_now - val_first) / max(val_first, 1)
    - val_stagnation_years: consecutive years with <5% valuation growth (resets on >5%)
    - rev_growth_3y: same pattern for revenue
    - rev_growth_long: same pattern for revenue
    - rev_stagnation_years: same pattern for revenue
    - deal_trend_3y: (deals_now - deals_3y_ago) / max(deals_3y_ago, 1)
    """
```

**Important unit notes:**
- `eoy_valuation` is in **millions** (from `deals.valuation_in_millions`)
- `revenue` is in **dollars** (from `revenue_cache.value`) — conversion to millions happens where needed in rule logic
- All growth rates are expressed as decimals (0.30 = 30%)

---

## 4. Rule Engine (`engine/`)

### 4.1 Rule Design Pattern (`engine/rules.py`)

Every rule is an isolated, pure function:

```python
def apply_rule(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Takes full dataset + relevant params, returns df with 'calculated_qot' updated.
    Sets df['last_rule_applied'] for records this rule modified.
    Returns the modified DataFrame.
    """
```

Each rule:
- Builds a boolean mask for qualifying records
- Only modifies `calculated_qot` where the mask is True AND the rule would change the value
- Tags modified records with the rule name in `last_rule_applied`
- Appends the rule name to the `rules_applied` list column for each affected record

### 4.2 Rule Pipeline (`engine/scoring.py`)

```python
RULE_PIPELINE = [
    # Phase 1: Base assignment
    ("base_quality",              apply_base_quality_stretch),
    ("sub_quality_upgrade",       apply_sub_quality_upgrades),
    ("mosaic_upgrade",            apply_mosaic_upgrades),

    # Phase 2: Upgrade rules
    ("revenue_upgrade",           apply_revenue_upgrades),
    ("public_revenue_upgrade",    apply_public_revenue_upgrades),
    ("valuation_upgrade",         apply_valuation_upgrades),       # unicorn/decacorn/growth
    ("tier1_vc_upgrade",          apply_tier1_vc_upgrades),

    # Phase 3: Advanced upgrade rules
    ("exceptional_val_growth",    apply_exceptional_val_growth),   # 200%+ growth, non-PE
    ("pe_hot_rules",              apply_pe_hot_rules),             # PE-specific Q5
    ("rev_growth_upgrade",        apply_rev_growth_upgrade),       # $100M+ rev + 150% growth
    ("stagnant_val_rev_check",    apply_stagnant_val_rev_check),   # stagnant val requires rev growth
    ("no_recent_funding_check",   apply_no_recent_funding_check),  # higher bar w/o recent deals

    # Phase 4: Exclusions and downgrades
    ("legacy_exclusion",          apply_legacy_exclusion),         # Legacy ≠ Q5
    ("legacy_penalty",            apply_legacy_penalty),           # cap legacy quality
    ("revenue_decline_downgrade", apply_revenue_decline_downgrade),
    ("stagnation_downgrade",      apply_stagnation_downgrade),     # rev + val stagnation
    ("val_decline_downgrade",     apply_val_decline_downgrade),    # VC valuation decline
    ("growth_rev_stagnation",     apply_growth_rev_stagnation),    # Growth segment: 3yr rev stagnation

    # Phase 5: Segment and acquisition rules
    ("segment_transition",        apply_segment_transition_rules), # Public→PE, taken private
    ("pe_deal_decline",           apply_pe_deal_decline),
    ("acquisition_degradation",   apply_acquisition_degradation),
]

def run_scoring(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Execute all enabled rules in pipeline order."""
    df["calculated_qot"] = df["quality_score"].copy()
    df["rules_applied"] = [[] for _ in range(len(df))]
    df["last_rule_applied"] = ""

    for rule_name, rule_fn in RULE_PIPELINE:
        # Check enable flag — base rules are always on, others check config
        enable_key = f"enable_{rule_name}"
        if enable_key in config and not config[enable_key]:
            continue
        df = rule_fn(df, config)

    return df
```

### 4.3 Comprehensive Rule Implementations

#### Phase 1: Base Assignment

**`apply_base_quality_stretch`** — Stretches current `quality_score` backwards across all years for each company. This is the `qot_calculator_2` baseline approach that achieves ~82%.

**`apply_sub_quality_upgrades`** — Hot/Iconic sub_quality → Q5:
```python
if params["upgrade_hot_to_5"]:
    mask = df["sub_quality"] == "Hot"
    df.loc[mask, "calculated_qot"] = 5

if params["upgrade_iconic_to_5"]:
    mask = df["sub_quality"] == "Iconic"
    df.loc[mask, "calculated_qot"] = 5
```

**`apply_mosaic_upgrades`** — Three-tier floor system:
```python
for threshold_key, floor_key in [
    ("mosaic_900_threshold", "mosaic_900_floor"),
    ("mosaic_750_threshold", "mosaic_750_floor"),
    ("mosaic_650_threshold", "mosaic_650_floor"),
]:
    mask = df["mosaic_score"] >= params[threshold_key]
    df.loc[mask, "calculated_qot"] = df.loc[mask, "calculated_qot"].clip(lower=params[floor_key])
```

#### Phase 2: Standard Upgrades

**`apply_revenue_upgrades`** — General revenue-based:
```python
mask = (
    (df["revenue"] >= params["rev_upgrade_min_revenue"]) &
    (df["rev_growth_3y"] >= params["rev_upgrade_growth_threshold"])
)
df.loc[mask, "calculated_qot"] = params["rev_upgrade_target_quality"]
```

**`apply_public_revenue_upgrades`** — Public company-specific:
```python
mask = (
    (df["segment"] == "Public") &
    (df["revenue"] >= params["public_rev_upgrade_min_revenue"]) &
    (df["rev_growth_3y"] >= params["public_rev_upgrade_growth_threshold"])
)
df.loc[mask, "calculated_qot"] = params["rev_upgrade_target_quality"]
```

**`apply_valuation_upgrades`** — Unicorn/Decacorn floors + valuation growth:
```python
# Unicorn floor
if params["enable_unicorn_upgrade"]:
    mask = df["is_unicorn"] & (df["calculated_qot"] < params["unicorn_upgrade_quality_floor"])
    df.loc[mask, "calculated_qot"] = params["unicorn_upgrade_quality_floor"]

# Decacorn floor
if params["enable_decacorn_upgrade"]:
    mask = df["is_decacorn"] & (df["calculated_qot"] < params["decacorn_upgrade_quality_floor"])
    df.loc[mask, "calculated_qot"] = params["decacorn_upgrade_quality_floor"]

# Valuation growth
if params["enable_val_growth_upgrade"]:
    mask = df["val_growth_3y"] >= params["val_growth_threshold"]
    if params["require_revenue_validation"]:
        mask &= df["revenue"] >= params["val_upgrade_min_revenue"]
    df.loc[mask, "calculated_qot"] = params["val_growth_upgrade_target"]
```

**`apply_tier1_vc_upgrades`**:
```python
mask = (
    (df["has_tier1_vc"]) &
    (df["segment"] != "PE") &
    (df["eoy_valuation"] >= params["tier1_vc_min_valuation"] / 1_000_000) &  # convert USD to millions
    (df["val_growth_3y"] >= params["tier1_vc_growth_threshold"])
)
df.loc[mask, "calculated_qot"] = params["tier1_vc_upgrade_target"]
```

#### Phase 3: Advanced Rules (from `assign_quality.py`)

**`apply_exceptional_val_growth`** — 200%+ 3yr valuation growth → Q5, non-PE only:
```python
mask = (
    (df["segment"] != "PE") &
    (df["val_growth_3y"] >= params["exceptional_val_growth_threshold"])
)
df.loc[mask, "calculated_qot"] = 5
```

**`apply_pe_hot_rules`** — PE companies need very high revenue to reach Q5:
```python
# High-rev PE: $50B+ revenue + 50%+ growth
mask_high = (
    (df["segment"] == "PE") &
    (df["revenue"] >= params["pe_hot_rev_threshold_high"]) &
    (df["rev_growth_3y"] >= params["pe_hot_growth_threshold_high"])
)
# Lower-rev PE: $20B+ revenue + 75%+ growth
mask_low = (
    (df["segment"] == "PE") &
    (df["revenue"] >= params["pe_hot_rev_threshold_low"]) &
    (df["rev_growth_3y"] >= params["pe_hot_growth_threshold_low"])
)
df.loc[mask_high | mask_low, "calculated_qot"] = 5
```

**`apply_rev_growth_upgrade`** — Exceptional revenue growth:
```python
mask = (
    (df["revenue"] >= params["rev_growth_upgrade_min_revenue"]) &
    (df["rev_growth_3y"] >= params["rev_growth_upgrade_threshold"])
)
df.loc[mask, "calculated_qot"] = 5
```

**`apply_stagnant_val_rev_check`** — For companies with stagnant valuations ($1B+, <10% growth), require exceptional revenue growth for Q5. Tiered by revenue stage:
```python
# From assign_quality.py: different thresholds by revenue stage
# Sub-$100M rev: 200%+ rev growth required
# $100M-$300M: 100%+ rev growth
# $300M-$1B: 60%+ rev growth
# $1B+: 40%+ rev growth
stagnant = (
    (df["eoy_valuation"] >= 1000) &  # $1B+ valuation (in millions)
    (df["val_growth_3y"] < params["stagnant_val_threshold"]) &
    (df["calculated_qot"] == 5)
)
# Downgrade Q5 companies that don't meet revenue growth requirements
# (specific threshold depends on revenue stage)
```

**`apply_no_recent_funding_check`** — Higher revenue growth bar for companies with no deals since 2022:
```python
# From assign_quality.py: companies with $1B+ valuation but no recent funding
# Even higher revenue growth thresholds than stagnant_val check:
# Sub-$100M rev: 300%+ growth
# $100M-$300M: 150%+
# $300M-$1B: 100%+
# $1B+: 70%+
no_recent = (
    (df["eoy_valuation"] >= 1000) &
    (df["years_since_last_deal"] >= (current_year - 2022)) &
    (df["calculated_qot"] == 5)
)
```

#### Phase 4: Downgrades

**`apply_legacy_exclusion`** — Legacy companies cannot be Q5:
```python
mask = (df["sub_quality"] == "Legacy") & (df["calculated_qot"] == 5)
df.loc[mask, "calculated_qot"] = 4
```

**`apply_legacy_penalty`** — Cap quality for legacy companies:
```python
mask = (df["sub_quality"] == "Legacy") & (df["calculated_qot"] > params["legacy_penalty_max_quality"])
df.loc[mask, "calculated_qot"] = params["legacy_penalty_max_quality"]
```

**`apply_revenue_decline_downgrade`**:
```python
mask = (
    (df["rev_growth_3y"] <= params["rev_decline_threshold"]) &
    (df["segment"].isin(params["rev_decline_segments"]))
)
df.loc[mask, "calculated_qot"] = (df.loc[mask, "calculated_qot"] - 1).clip(lower=1)
```

**`apply_stagnation_downgrade`** — Multi-year stagnation:
```python
rev_stagnant = df["rev_stagnation_years"] >= params["rev_stagnation_years_threshold"]
val_stagnant = df["val_stagnation_years"] >= params["val_stagnation_years_threshold"]
mask = rev_stagnant | val_stagnant
df.loc[mask, "calculated_qot"] = (
    df.loc[mask, "calculated_qot"] - params["stagnation_downgrade_amount"]
).clip(lower=1)
```

**`apply_val_decline_downgrade`** — VC valuation decline:
```python
mask = (
    (df["segment"] == "VC") &
    (df["val_growth_3y"] <= params["val_decline_threshold"])
)
df.loc[mask, "calculated_qot"] = (df.loc[mask, "calculated_qot"] - 1).clip(lower=1)
```

**`apply_growth_rev_stagnation`** — Growth segment: revenue stagnation 3+ years:
```python
mask = (
    (df["segment"] == "Growth") &
    (df["rev_stagnation_years"] >= params["growth_rev_stagnation_years"])
)
df.loc[mask, "calculated_qot"] = (df.loc[mask, "calculated_qot"] - 1).clip(lower=1)
```

#### Phase 5: Segment & Acquisition

**`apply_segment_transition_rules`**:
```python
# Public → PE downgrade
if params["enable_public_to_pe_downgrade"]:
    mask = (
        (df["prev_segment"] == "Public") &
        (df["segment"] == "PE") &
        (df["segment_changed"]) &
        (df["calculated_qot"] >= params["public_to_pe_min_quality"])
    )
    df.loc[mask, "calculated_qot"] -= params["public_to_pe_downgrade_amount"]

# Taken private cap
if params["enable_taken_private_cap"]:
    mask = (df["prev_segment"] == "Public") & (df["segment"] == "PE")
    df.loc[mask, "calculated_qot"] = df.loc[mask, "calculated_qot"].clip(upper=3)
```

**`apply_pe_deal_decline`**:
```python
mask = (
    (df["segment"] == "PE") &
    (df["deal_trend_3y"] <= params["pe_deal_decline_threshold"])
)
df.loc[mask, "calculated_qot"] = (df.loc[mask, "calculated_qot"] - 1).clip(lower=1)
```

**`apply_acquisition_degradation`** — Q5 acquired companies drop after delay:
```python
mask = (
    (df["exit_type"].isin(["Acquired", "Acq - P2P", "Acq - Pending", "Merger"])) &
    (df["years_since_exit"] >= params["acquisition_degradation_delay"]) &
    (df["calculated_qot"] > params["acquisition_degradation_target"])
)
df.loc[mask, "calculated_qot"] = params["acquisition_degradation_target"]
```

### 4.4 Spread Quality (`engine/spread.py`)

Ported from `qot_calculator/spread_quality.py`. Applied as a post-processing step after rule assignment. Uses fixed defaults from the existing pipeline (configurable in V2).

**Progress multiplier system** (0.0 → 1.0 based on milestones):
```python
VALUATION_MILESTONES = [
    (10_000, 1.0),  # Decacorn ($10B+)
    (1_000,  0.8),  # Unicorn ($1B+)
    (500,    0.7),  # $500M+
    (100,    0.5),  # $100M+
    (10,     0.3),  # $10M+
]

REVENUE_MILESTONES = [
    (1_000_000_000, 1.0),   # $1B+
    (500_000_000,   0.9),
    (200_000_000,   0.8),
    (100_000_000,   0.7),
    (50_000_000,    0.6),
    (30_000_000,    0.5),
    (10_000_000,    0.4),
]
```

**Exit handling:**
- Exit year: boost quality based on exit value ($10B+ → Q5, $5B+ → Q4.5, $1B+ → Q4, $500M+ → Q3.5)
- Post-exit: maintain quality × decay factor (0.95 for $1B+ exits, 0.9 for $500M+, 0.8 otherwise)

---

## 5. Comparison Engine (`engine/compare.py`)

Compares against **two** production sources.

### 5.1 QOT Table Comparison

```python
def compare_against_qot_table(calculated_df: pd.DataFrame, conn) -> dict:
    """Query: SELECT company_id, year, qot FROM qot
    Join on (company_id, year).
    Returns:
    - overall_match_rate: float
    - by_segment: dict[str, float]
    - by_quality: dict[int, float]
    - by_year: dict[int, float]
    - delta_from_baseline: float (vs 82.25%)
    - mismatches: DataFrame (company_id, company_name, segment, year,
                             calculated_qot, db_qot, direction, rules_applied)
    """
```

### 5.2 Companies Table Comparison

```python
def compare_against_companies_table(calculated_df: pd.DataFrame, conn) -> dict:
    """Query: SELECT company_id, quality, sub_quality FROM companies
              WHERE delete = false OR delete IS NULL
    Compares the MOST RECENT year per company against companies.quality.

    Quality mapping:
        companies.quality   calculated_qot
        'Low'              → 1
        'Medium'           → 2
        'High'             → 3
        'Top'              → 4–5

    Sub-quality analysis:
        - Hot: companies currently at Q5 with sub_quality = 'Hot'
        - Iconic: companies that achieved Q5/Hot at some point historically
          (may or may not still be Q5)
        - Legacy: old companies that may need penalty

    Returns:
    - quality_match_rate: float
    - sub_quality_breakdown: dict showing Hot/Iconic/Legacy accuracy
    - iconic_analysis: DataFrame showing which Iconic companies were
      correctly identified as having historical Q5 status
    """
```

### 5.3 Combined Results

```python
def compute_all_comparisons(calculated_df: pd.DataFrame, conn) -> dict:
    """Runs both comparisons, returns unified results dict for the UI."""
    return {
        "qot_table": compare_against_qot_table(calculated_df, conn),
        "companies_table": compare_against_companies_table(calculated_df, conn),
        "calculated_df": calculated_df,
    }
```

---

## 6. UI Components

### 6.1 Parameter Inputs (`components/parameter_inputs.py`)

8 tabs matching the PRD categories. Modeled on the strength2 `parameter_inputs.py` pattern.

**Tabs:**
1. Base Quality Assignment — always active
2. Revenue Upgrades — enable toggle
3. Valuation Upgrades — enable toggle
4. Downgrade Rules — enable toggle
5. Segment Rules — enable toggle
6. Acquisition Rules — enable toggle
7. Tier 1 VC Rules — enable toggle
8. Advanced Rules — individual enable toggles per sub-rule

### 6.2 Visualizations (`components/visualizations.py`)

| Chart | Type | Description |
|---|---|---|
| QOT Distribution | Plotly grouped bar | Side-by-side: calculated vs DB, grouped by Q1–Q5 |
| Match Rate by Year | Plotly line | One point per year, with baseline reference line |
| Rule Impact | Plotly horizontal bar | Record count per rule that was applied |
| Company Timeline | Plotly multi-axis | QOT line + revenue/valuation area + DB QOT overlay |
| Match Rate Summary | Streamlit `st.metric()` | Cards for overall, per-segment, delta from baseline |
| Quality Tier Comparison | Plotly heatmap | Confusion matrix: calculated tier vs companies.quality |
| Sub-quality Analysis | Plotly bar | Hot/Iconic/Legacy detection accuracy |

### 6.3 Diff Explorer (`components/diff_table.py`)

```python
def render_diff_table(mismatches: pd.DataFrame):
    """Interactive mismatch table.
    Columns: company_name, segment, year, calculated_qot, db_qot, direction, rules_applied
    Filters: segment, quality tier, rule name, direction (upgraded/downgraded)
    Sortable by any column.
    """
```

### 6.4 Validation (`components/validation.py`)

```python
def validate_config(config: dict) -> list[str]:
    """Returns error strings. Empty = valid.
    - Quality values are 1–5
    - Thresholds are non-negative
    - Mosaic thresholds in descending order (900 > 750 > 650)
    - Revenue thresholds in USD (not millions) — warn if < 1000
    - Downgrade amounts don't exceed quality range
    """
```

---

## 7. App Flow (`app.py`)

### Layout

```
┌─────────────────────────────────────┬──────────────────────────────────┐
│  SIDEBAR                            │  MAIN AREA                       │
│                                     │                                  │
│  [Refresh Data]                     │  Tab: Parameters | Results       │
│  Last refresh: 2026-03-16 10:30    │                                  │
│  Records: 423,891                   │  [Parameters Tab]                │
│  ─────────────────                  │  8 sub-tabs with controls        │
│  Validation Status: ✅              │                                  │
│  ─────────────────                  │  [Results Tab]                   │
│  [Run Scoring]                      │  QOT Table Match Rate Panel      │
│  ─────────────────                  │  Companies Table Match Panel     │
│  Config: Export | Import | Reset    │  Visualizations                  │
│  ─────────────────                  │  Diff Explorer                   │
│  Experiments:                       │  Company Timeline                │
│  • baseline_v1  82.25%             │                                  │
│  • rev_rules    84.10%             │                                  │
│  ─────────────────                  │                                  │
│  Company Lookup: [search]           │                                  │
└─────────────────────────────────────┴──────────────────────────────────┘
```

### Execution Flow

```python
def main():
    st.set_page_config(layout="wide", page_title="QOT Testing Suite")

    # Sidebar
    with st.sidebar:
        # Data management
        if st.button("Refresh Data"):
            conn = get_cached_connection()
            df = build_temporal_metrics(conn)
            st.cache_data.clear()  # invalidate cached parquet
            st.success(f"Built {len(df):,} records")

        render_data_status()  # last refresh time, record count
        st.divider()

        # Scoring
        render_validation_status(st.session_state.config)
        if st.button("Run Scoring", disabled=not is_valid):
            run_scoring_pipeline()
        st.divider()

        # Config management
        render_config_controls()
        render_experiment_list()
        st.divider()

        # Company lookup
        render_company_lookup()

    # Main area
    tab_params, tab_results = st.tabs(["Parameters", "Results"])

    with tab_params:
        config = render_all_parameter_tabs()  # 8 sub-tabs
        st.session_state.config = config

    with tab_results:
        if st.session_state.results is not None:
            render_qot_match_panel(st.session_state.results["qot_table"])
            render_companies_match_panel(st.session_state.results["companies_table"])
            render_visualizations(st.session_state.results)
            render_diff_table(st.session_state.results["qot_table"]["mismatches"])

def run_scoring_pipeline():
    df = load_temporal_metrics()  # from parquet
    df = run_scoring(df, st.session_state.config)
    df = apply_spread_quality(df)  # default spread logic
    conn = get_cached_connection()
    results = compute_all_comparisons(df, conn)
    st.session_state.results = results
```

---

## 8. Config Management (`utils/config.py`)

```python
DEFAULT_CONFIG = {
    # 1. Base Quality
    "upgrade_hot_to_5": True,
    "upgrade_iconic_to_5": True,
    "mosaic_900_floor": 4, "mosaic_750_floor": 3, "mosaic_650_floor": 2,
    "mosaic_900_threshold": 900.0, "mosaic_750_threshold": 750.0, "mosaic_650_threshold": 650.0,

    # 2. Revenue Upgrades
    "enable_revenue_upgrade": False,
    "rev_upgrade_min_revenue": 1_000_000_000,
    "rev_upgrade_growth_threshold": 0.30,
    "rev_upgrade_target_quality": 5,
    "public_rev_upgrade_enabled": False,
    "public_rev_upgrade_min_revenue": 5_000_000_000,
    "public_rev_upgrade_growth_threshold": 0.20,

    # 3. Valuation Upgrades
    "enable_unicorn_upgrade": False,
    "unicorn_upgrade_quality_floor": 4,
    "enable_decacorn_upgrade": False,
    "decacorn_upgrade_quality_floor": 5,
    "enable_val_growth_upgrade": False,
    "val_growth_threshold": 2.0,
    "val_growth_upgrade_target": 5,
    "require_revenue_validation": False,
    "val_upgrade_min_revenue": 500_000_000,

    # 4. Downgrade Rules
    "enable_revenue_decline_downgrade": False,
    "rev_decline_threshold": -0.20,
    "rev_decline_segments": ["Public"],
    "enable_stagnation_downgrade": False,
    "rev_stagnation_years_threshold": 5,
    "val_stagnation_years_threshold": 5,
    "stagnation_downgrade_amount": 1,

    # 5. Segment Rules
    "enable_public_to_pe_downgrade": True,
    "public_to_pe_min_quality": 4,
    "public_to_pe_downgrade_amount": 1,
    "enable_pe_deal_decline_downgrade": False,
    "pe_deal_decline_threshold": -0.50,
    "enable_taken_private_cap": False,

    # 6. Acquisition Rules
    "enable_acquisition_degradation": True,
    "acquisition_degradation_delay": 2,
    "acquisition_degradation_target": 4,

    # 7. Tier 1 VC Rules
    "enable_tier1_vc_upgrade": False,
    "tier1_vc_min_valuation": 500_000_000,
    "tier1_vc_growth_threshold": 0.50,
    "tier1_vc_upgrade_target": 5,

    # 8. Advanced Rules
    "enable_exceptional_val_growth": True,
    "exceptional_val_growth_threshold": 2.0,
    "enable_pe_hot_rules": True,
    "pe_hot_rev_threshold_high": 50_000_000_000,
    "pe_hot_growth_threshold_high": 0.50,
    "pe_hot_rev_threshold_low": 20_000_000_000,
    "pe_hot_growth_threshold_low": 0.75,
    "enable_rev_growth_upgrade": True,
    "rev_growth_upgrade_min_revenue": 100_000_000,
    "rev_growth_upgrade_threshold": 1.50,
    "enable_legacy_exclusion": True,
    "enable_legacy_penalty": False,
    "legacy_penalty_max_quality": 3,
    "enable_val_decline_downgrade": True,
    "val_decline_threshold": -0.30,
    "enable_growth_rev_stagnation": True,
    "growth_rev_stagnation_years": 3,
    "enable_stagnant_val_rev_check": True,
    "stagnant_val_threshold": 0.10,
    "enable_no_recent_funding_check": True,
}
```

---

## 9. Caching Strategy (`utils/caching.py`)

```python
@st.cache_resource
def get_cached_connection():
    """DB connection. Not serializable — use cache_resource."""

@st.cache_data(ttl=3600)
def load_temporal_metrics() -> pd.DataFrame:
    """Load from data/temporal_metrics.parquet. 1-hour TTL.
    Falls back to error message if parquet doesn't exist (need to Refresh Data first).
    """
    return pd.read_parquet("data/temporal_metrics.parquet")

@st.cache_data(ttl=3600)
def load_production_qot(_conn) -> pd.DataFrame:
    """Query qot table for comparison. Underscore prefix excludes conn from hash."""

@st.cache_data(ttl=3600)
def load_production_companies(_conn) -> pd.DataFrame:
    """Query companies table (quality, sub_quality) for comparison."""
```

Scoring and comparison are **not cached** — params change on every interaction.

---

## 10. Performance

### Targets (from PRD)

| Operation | Target | Expected |
|---|---|---|
| Data refresh (DB → parquet) | < 60s | ~15–30s |
| Parquet load | < 2s | < 1s |
| Scoring run (all rules) | < 10s | < 3s |
| DB comparison queries | < 5s | < 2s |
| Total interactive cycle | < 15s | < 5s |

### Approach

- **Parquet** for data storage — columnar format, ~5x faster reads than CSV, smaller on disk
- **Vectorized Pandas** throughout — no Python loops, all rules are mask + assignment
- **Pre-computed trajectories** — growth rates and stagnation counts baked into parquet, not recomputed per scoring run
- **Cached DB queries** — production comparison data cached with 1-hour TTL
- **Streaming SQL** — large queries use `fetchmany(50_000)` chunks (from `q7_simple_deals.py` pattern)

### Memory

- Parquet at ~10–15MB compressed fits easily in memory
- Expanded DataFrame: ~200–400MB for 500K rows × 40+ columns
- Production comparison tables: ~50MB
- Peak: ~500MB — well within local development constraints

---

## 11. Implementation Plan

### Phase 1: Data Pipeline
1. Set up project structure, `requirements.txt`, `.env`, `.gitignore`
2. `pipeline/segmentation.py` — port segmentation SQL from qot_calculator
3. `pipeline/metrics.py` — port and enhance metrics computation
4. `pipeline/build_metrics.py` — orchestrator, parquet output
5. `utils/caching.py` + `utils/data_loader.py`

### Phase 2: Rule Engine
6. `engine/rules.py` — implement all 20+ rules as isolated functions
7. `engine/scoring.py` — pipeline orchestrator
8. `engine/spread.py` — port spread_quality logic
9. `engine/compare.py` — dual comparison engine (qot + companies tables)

### Phase 3: UI
10. `utils/config.py` — full default config, serialization
11. `components/parameter_inputs.py` — 8 parameter tabs
12. `components/validation.py` — config validation
13. `components/visualizations.py` — all charts
14. `components/diff_table.py` — mismatch explorer

### Phase 4: Integration
15. `app.py` — wire everything together
16. Config import/export/reset
17. Experiment save/compare
18. Company lookup + timeline

---

## 12. Dependencies

```
streamlit>=1.28.0
pandas>=1.5.0
numpy>=1.21.0
pyarrow>=14.0.0
plotly>=5.0.0
psycopg2-binary>=2.9.0
pyyaml>=6.0
python-dotenv>=1.0.0
```

---

## 13. Key Differences from Strength 2.0 Testing Suite

| Aspect | Strength 2.0 Suite | QOT Testing Suite |
|---|---|---|
| Scoring approach | ML-based (sigmoid, regression) | Rule-based (thresholds, conditionals) |
| Ground truth | No external comparison | Production DB match rate (two tables) |
| Data shape | Per-candidate (flat) | Per-company-year (temporal) |
| Data pipeline | External (DB only) | App-managed (DB → parquet) |
| Parameter count | ~25 | ~60+ |
| Key metric | Score distribution | Match rate vs production |
| Visualization focus | Component breakdown, scatter | Timeline, year-over-year, diff, confusion matrix |
| Data size | ~10K candidates | ~100K–500K company-year records |
| Deployment | AWS App Runner | Local only (V1) |

The architectural pattern (Streamlit + tabs + sidebar + caching) transfers directly. The data pipeline, scoring engine, and comparison layer are domain-specific.
