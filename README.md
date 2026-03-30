# QOT Testing Suite

Interactive parameter tuning tool for **Quality Over Time (QOT)** scoring rules. Experiment with different scoring configurations, compare results against production data, and publish finalized scores to the database.

## What is QOT?

QOT assigns every company a quality score from **Q1** (lowest) to **Q5** (highest) for each year in their history. Quality is determined by a pipeline of rules that evaluate company metrics like revenue growth, valuation milestones, Mosaic scores, VC backing, and segment transitions.

This tool lets you:
- **Tune** 80+ scoring parameters across 10 categories
- **Compare** calculated scores against production QOT values in real-time
- **Visualize** match rates by segment, quality level, year, and sub-quality
- **Publish** a finalized config to the database as a `calculated_qot` table
- **Export/import** configs as JSON for reproducibility

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd qot_testing_suite
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure database

Copy the example environment file and add your database credentials:

```bash
cp .env.example .env
```

Edit `.env` with your PostgreSQL connection string:

```
DATABASE_URL=postgresql://username:password@host:5432/dbname
```

The database must contain the following tables:
- `companies` (company_id, company_name, mosaic_score, quality_score, sub_quality, found_yr, ...)
- `deals` (deal_id, funded_company_id, deal_date, valuation_in_millions, funding_round, ...)
- `deal_link` (deal_id, investor_name)
- `revenue_cache` + `revenue` (company_id, year, value, source)
- `qot` (company_id, year, qot) — production scores to compare against

### 3. Run the app

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### 4. First run

1. Click **Refresh Data** in the sidebar to build the temporal metrics cache (pulls from DB, takes ~1-2 minutes)
2. Adjust parameters in the **Parameters** tab
3. Click **Run Scoring** to calculate quality scores and compare against production
4. View results in the **Results** tab
5. See full parameter documentation in the **Reference** tab

## How Scoring Works

Scoring runs as a **pipeline of 26 rules** applied in order:

```
Phase 1: Base Quality
  Set baseline (quality table / mosaic only / qot table / blank slate)
  Sub-quality upgrades (Hot -> Q5, Iconic -> Q5)
  Mosaic score floors (900+ -> Q4, 750+ -> Q3, 650+ -> Q2)

Phase 2: Upgrade Rules
  Revenue growth upgrades (9 buckets, each adds +1)
  Public company revenue upgrade
  Valuation milestones (unicorn floor, decacorn floor, growth target)
  Tier 1 VC involvement (per funding stage, adds +1)

Phase 3: Advanced Rules
  Exceptional valuation growth -> Q5
  PE-specific Q5 rules
  Exceptional revenue growth -> Q5
  Stagnant valuation checks
  No recent funding checks

Phase 4: Downgrade & Guard Rules
  Revenue decline downgrade (-1)
  Stagnation downgrade (-1)
  Legacy exclusion / penalty (cap)
  Q5 validation guards (decacorn, unicorn)

Phase 5: Public Company Fine-Tuning
  Low-growth public downgrade
  Large-revenue Q1 public upgrade

Phase 6: Segment & Acquisition
  Public -> PE transition downgrade
  PE deal decline downgrade
  Acquisition quality degradation
```

**Key principle:** Rules run in order. Later rules can override earlier ones. The `last_rule_applied` column shows which rule had the final say.

**+1 rules** (revenue buckets, T1 VC) add a point to the current score. **Target rules** (unicorn floor, decacorn floor) set quality to a specific level. **Downgrade rules** subtract points or cap quality. Quality is always clamped to 1-5.

## Publishing Scores to the Database

Once you've found a config that produces good match rates, you can write the results to the database.

### From the UI

1. Run scoring with your desired config
2. In the sidebar, enter a **Config name** under "Publish"
3. Click **Write to DB**
4. Results are written to the `calculated_qot` table, and the config is saved to `qot_configs`

### From the command line

Export your config from the UI (sidebar > Export), then:

```bash
python scripts/run_from_config.py qot_config.json "My Experiment v3"
```

This runs the full pipeline headless and writes results to the database.

### Database tables created

**`calculated_qot`** — one row per company per year per config:

| Column | Type | Description |
|--------|------|-------------|
| company_id | integer | Company identifier |
| year | integer | Year |
| calculated_qot | integer (1-5) | Calculated quality score |
| last_rule_applied | varchar | Which rule had the final say |
| baseline_strategy | varchar | Which baseline was used |
| config_hash | varchar(64) | SHA-256 hash of the config |
| run_timestamp | timestamp | When scoring was run |

**`qot_configs`** — one row per unique config:

| Column | Type | Description |
|--------|------|-------------|
| config_hash | varchar(64) | SHA-256 hash (primary key) |
| config_json | jsonb | Full config parameters |
| name | varchar | User-friendly label |
| match_rate | numeric | Match rate at time of publish |
| created_at | timestamp | When config was saved |

Multiple configs can coexist — each produces its own set of rows keyed by `config_hash`. Re-running the same config is idempotent.

### Querying results

```sql
-- Get latest calculated quality for all companies
SELECT c.company_name, cq.year, cq.calculated_qot
FROM calculated_qot cq
JOIN companies c ON c.company_id = cq.company_id
WHERE cq.config_hash = (
    SELECT config_hash FROM qot_configs ORDER BY created_at DESC LIMIT 1
)
ORDER BY c.company_name, cq.year;

-- Compare calculated vs production
SELECT cq.company_id, cq.year,
       cq.calculated_qot, q.qot AS production_qot,
       cq.calculated_qot - q.qot AS diff
FROM calculated_qot cq
JOIN qot q ON q.company_id = cq.company_id AND q.year = cq.year
WHERE cq.config_hash = 'your_hash_here'
  AND cq.calculated_qot != q.qot;

-- Compare two config runs
SELECT a.company_id, a.year,
       a.calculated_qot AS config_a,
       b.calculated_qot AS config_b
FROM calculated_qot a
JOIN calculated_qot b
  ON a.company_id = b.company_id AND a.year = b.year
WHERE a.config_hash = 'hash_a' AND b.config_hash = 'hash_b'
  AND a.calculated_qot != b.calculated_qot;
```

## Project Structure

```
qot_testing_suite/
├── app.py                    # Streamlit entry point
├── requirements.txt          # Python dependencies
├── .env.example              # Database config template
│
├── engine/                   # Scoring engine
│   ├── rules.py              # 26 scoring rule functions
│   ├── scoring.py            # Pipeline orchestrator
│   ├── spread.py             # Temporal quality spreading
│   ├── compare.py            # Production comparison logic
│   └── writer.py             # Database write-back
│
├── pipeline/                 # Data pipeline
│   ├── build_metrics.py      # Full pipeline runner
│   ├── metrics.py            # DB queries + metric computation
│   └── segmentation.py       # Company segment classification
│
├── components/               # Streamlit UI components
│   ├── parameter_inputs.py   # 10 parameter tabs
│   ├── parameter_reference.py # Full documentation
│   ├── validation.py         # Config validation
│   ├── visualizations.py     # Plotly charts
│   └── diff_table.py         # Score comparison table
│
├── utils/                    # Shared utilities
│   ├── config.py             # Default config + export/import
│   ├── caching.py            # DB connection + data caching
│   └── data_loader.py        # Data status helpers
│
├── scripts/
│   └── run_from_config.py    # CLI: score + write from JSON config
│
├── tests/
│   └── test_scoring.py       # 62 tests covering all rules
│
└── data/                     # Generated data (gitignored)
    └── temporal_metrics.parquet
```

## Configuration

All 80+ parameters are documented in the **Reference** tab of the app. Key categories:

| Category | What it controls |
|----------|-----------------|
| **Base Quality** | Baseline strategy, sub-quality upgrades, Mosaic floors |
| **Revenue Upgrades** | 9 revenue buckets with independent growth thresholds |
| **Valuation Upgrades** | Unicorn/decacorn floors, valuation growth targets |
| **Downgrade Rules** | Revenue decline, stagnation downgrades |
| **Segment Rules** | Public-to-PE transitions, taken-private caps |
| **Acquisition Rules** | Post-acquisition quality degradation |
| **Tier 1 VC** | Editable VC firm list, per-stage quality upgrades |
| **Advanced Rules** | Exceptional growth, PE-specific paths, legacy penalties |
| **Q5 Validation** | Guards preventing unearned Q5 scores |
| **Public Fine-Tuning** | Low-growth downgrades, large-revenue upgrades |

Configs can be exported as JSON and imported later for reproducibility.

## Testing

Run the test suite (62 tests, no database required):

```bash
python -m pytest tests/test_scoring.py -v
```

Tests cover:
- Default config execution
- All 4 baseline strategies
- Each of 26 rules individually + all enabled together
- All 9 revenue buckets with 1y/3y growth periods
- Full pipeline across all baselines
- Edge cases (empty data, nulls, NaNs, extreme values, out-of-range scores)
- 50 random config permutations (fuzz testing)

## Baseline Strategies

| Strategy | Starting score | Use case |
|----------|---------------|----------|
| **quality_table** | `companies.quality_score` stretched across all years | Default. ~82% match rate baseline |
| **mosaic_only** | Derived from Mosaic score thresholds (caps at Q4) | Test how much Mosaic alone explains quality |
| **qot_table** | Production QOT values, fallback to quality_score | Test how rules modify existing production scores |
| **blank_slate** | Everything starts at Q1 | See which rules actually drive quality from scratch |

## Tier 1 VC Firms

The default list includes 23 firms (Sequoia, a16z, Accel, Benchmark, etc.). You can add or remove firms in the UI. When enabled, companies with T1 VC involvement at selected funding stages get +1 quality:

- Seed, Series A, Series B, Series C, Series D
- Late Stage (Series E+), Growth Equity, PE

## Environment

- **Python:** 3.8+
- **Database:** PostgreSQL (tested with AWS RDS)
- **Key constraint:** `numpy<2` (required for compatibility with current pandas/pyarrow versions)
