# QOT Scoring Methodology

## Summary

- The QOT (Quality Over Time) system assigns every software company a quality score (Q1-Q5) and a sub-quality designation (Hot, Iconic, Incumbent, Legacy, or none) for every year from founding to present.
- Quality scores are computed through a deterministic 16-step pipeline that segments companies, computes metrics, assigns base quality from mosaic scores, promotes exceptional companies to Q5, validates and guards against false positives, applies decline-based drops, handles acquisition degradation, and assigns sub-quality labels.
- The system runs as a Streamlit app with a configurable scoring engine. The canonical configuration is SPEC_ALIGNED_CONFIG.

**Hook:** QOT scores every software company Q1-Q5 per year using a 16-step deterministic pipeline that combines mosaic scores, valuation, revenue, growth trajectories, VC backing, and segment-aware rules.

---

## Quality Tiers

| Tier | Label | Description |
|------|-------|-------------|
| Q1 | Low | Lowest quality |
| Q2 | Medium | Below average |
| Q3 | High | Above average |
| Q4 | Top | Top quality |
| Q5 | Top + Hot | Highest quality, earned through promotion criteria |

All quality scores are integers clamped to the range 1-5 after all rules execute.

---

## Sub-Quality Designations

Sub-quality only applies to companies that achieved Q4+ (Top) in at least one year of their history. Companies that never reached Q4 receive no sub-quality designation.

| Designation | Definition | Quality Range |
|-------------|-----------|---------------|
| Hot | Currently exceptional, earned through Q5 promotion criteria | Q5 |
| Iconic | Recently Hot (within 5 years) with top-25th-percentile growth relative to segment peers, still category-defining | Q4 |
| Incumbent | Was once Hot/Top but growth has plateaued, category leader no longer innovating | Q3-Q4 |
| Legacy | Was once Hot/Top but has significantly declined, or has been Q3 Incumbent for 5+ consecutive years | Q1-Q2 (or Q3 after long stagnation) |
| None | Company never achieved Q4+ in any year | Any |

---

## Pipeline Execution Order

The system runs 16 rules in strict sequence, grouped into 7 phases. Each rule reads the current state and may modify `calculated_qot` or `calculated_sub_quality`. The pipeline is defined as `SPEC_RULE_PIPELINE` in `engine/scoring.py`.

```
Phase 1: Base Quality
  1. apply_baseline (mosaic thresholds: 850/650/500)
  2. apply_no_mosaic_fallback (point-based system)
  3. apply_mosaic_upgrades (floor enforcement)

Phase 2: Q5 Promotions
  4. apply_q5_promotions (10 compound paths across 3 segment groups)

Phase 3: Q5 Validation and Guards
  5. apply_stagnant_val_rev_check
  6. apply_legacy_exclusion
  7. apply_rev_declining_exclusion

Phase 4: Quality Drops
  8.  apply_stagnation_downgrade (segment-aware)
  9.  apply_val_decline_downgrade (VC valuation decline)
  10. apply_revenue_decline_downgrade (Public revenue decline)
  11. apply_growth_rev_stagnation (Growth segment revenue)
  12. apply_pe_deal_decline (PE deal activity)
  13. apply_segment_transition_rules (taken-private cap)

Phase 5: Acquisition
  14. apply_acquisition_degradation (Q5 to Q4 after 2 years)

Phase 6: Override
  15. apply_current_year_override (manual overrides, currently disabled)

Phase 7: Sub-Quality
  16. apply_sub_quality_assignment (Hot/Iconic/Incumbent/Legacy)
```

---

## Step 1: Company Segmentation

**Script:** `pipeline/segmentation.py`

Assigns a segment to each company-year based on cumulative deal history. Segments are evaluated in priority order and the first match wins.

| Priority | Segment | Criteria |
|----------|---------|----------|
| 1 | Acquired | Has acquisition deal (Acquired, Acq - P2P, Acq - Pending, Merger) |
| 2 | PE | More PE deals than VC deals, OR has PE acquisition/take-private |
| 3 | Public | Has IPO deal OR IPO year reached (unless subsequently taken private) |
| 4 | Growth | Early VC + late-stage funding + $1B+ valuation, OR early VC + $10B+ valuation |
| 5 | VC | Has early-stage VC (Seed through Series D) |
| 6 | Other | Has deals but does not fit any above segment |
| 7 | Uncategorized | No deal data |

The segmentation step also tracks two additional fields per company-year:

- `prev_segment` - the segment assigned in the prior year
- `segment_changed` - boolean flag indicating whether a segment transition occurred

---

## Step 2: Temporal Metrics

**Script:** `pipeline/metrics.py`

For each company-year, the system computes raw metrics and derived trajectory metrics from the database.

### Raw Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| End-of-year valuation | Millions USD | Highest valuation that year, forward-filled from last known value |
| End-of-year deal size | Millions USD | Size of deals closed that year |
| Deal count | Integer | Number of deals closed that year |
| Revenue | USD | Annual revenue, prioritized by source quality (see below) |
| VC Quality | Boolean | Whether backed by any of the 23 named VCs (Tier 1 + Tier 2) |
| Unicorn status | Boolean | Valuation >= $1B |
| Decacorn status | Boolean | Valuation >= $10B |
| Exit info | String | IPO, Acquired, etc. |

### Revenue Source Priority

Revenue values are selected from the highest-confidence source available. When multiple sources exist, the system uses the one with the highest confidence weight.

| Source | Confidence Weight |
|--------|------------------|
| User-provided / Polygon | 1.0 |
| CB Insights / Calculated | 0.3 |
| Initial | 0.2 |
| OpenAI | 0.1 |

### Derived Trajectory Metrics

| Metric | Formula | Notes |
|--------|---------|-------|
| 3-year valuation growth (`val_growth_3y`) | `(current_val - val_3yr_ago) / max(val_3yr_ago, 1)` | Expressed as a decimal (1.0 = 100% growth) |
| 3-year revenue growth (`rev_growth_3y`) | `(current_rev - rev_3yr_ago) / max(rev_3yr_ago, 1)` | Same formula as valuation growth |
| Valuation stagnation years | Integer | Consecutive years with < 5% YoY valuation growth |
| Revenue stagnation years | Integer | Consecutive years with < 5% YoY revenue growth |
| Deal trend 3y | Float | 3-year deal activity trend |

Stagnation is defined as consecutive years with less than 5% year-over-year growth. The counter resets to zero whenever a year exceeds 5% growth.

---

## Step 3: Assign Base Quality

**Function:** `apply_base_mosaic_only()` in `engine/rules.py`

Maps the company's mosaic score directly to a base quality tier.

| Mosaic Score | Quality |
|-------------|---------|
| 850+ | Q4 (Top) |
| 650-849 | Q3 (High) |
| 500-649 | Q2 (Medium) |
| < 500 | Q1 (Low) |

Companies without mosaic scores (null or 0) receive Q1 initially. The no-mosaic fallback in Step 4 handles these companies.

---

## Step 4: No-Mosaic Fallback

**Function:** `apply_no_mosaic_fallback()` in `engine/rules.py`

For companies where `mosaic_score` is null or 0, the system uses a point-based scoring system that aggregates signals from valuation, revenue, growth, and VC backing.

### Point Accumulation

Points are awarded across four categories. Within the valuation and revenue categories, only the highest-qualifying tier is awarded (mutually exclusive). Growth and VC signals are additive.

**Valuation tier (mutually exclusive, highest wins):**

| Condition | Points |
|-----------|--------|
| Unicorn ($1B+ valuation) | +3 |
| $500M+ valuation | +2 |
| $100M+ valuation | +1 |

**Revenue tier (mutually exclusive, highest wins):**

| Condition | Points |
|-----------|--------|
| $100M+ revenue | +2 |
| $50M+ revenue | +1 |

**Growth signals (additive):**

| Condition | Points |
|-----------|--------|
| 30%+ 3-year valuation growth | +1 |
| 30%+ 3-year revenue growth | +1 |

**VC backing (additive):**

| Condition | Points |
|-----------|--------|
| Backed by any of 23 named VCs (Tier 1 + Tier 2) | +1 |

**Maximum possible score: 3 + 2 + 1 + 1 + 1 = 8 points**

### Points to Quality Mapping

| Points | Quality |
|--------|---------|
| 4+ | Q4 (Top) |
| 2-3 | Q3 (High) |
| 1 | Q2 (Medium) |
| 0 | Q1 (Low) |

---

## Step 5: Promote to Q5 (Hot)

**Function:** `apply_q5_promotions()` in `engine/rules.py`

There is no minimum quality floor for Q5 promotion. Any company meeting the compound criteria for its segment receives Q5. Each promotion is tagged with the specific path that triggered it for auditability.

**Acquired companies** use their last non-Acquired segment for Q5 path evaluation. For example, if Wiz was "Growth" before being acquired, it is evaluated against the VC/Growth Q5 paths. If Slack was "Public" before acquisition, it uses the Public paths. The system looks back through the company's full segment history to find the most recent non-Acquired segment. The acquisition degradation rule (Step 8) separately handles post-acquisition quality decay.

### VC/Growth Companies (5 paths)

| Path | Tag | Conditions (all must be true) |
|------|-----|-------------------------------|
| 1 | `q5_vc_decacorn_val_growth_rev` | Decacorn ($10B+ valuation) AND 30%+ `val_growth_3y` AND $500M+ revenue |
| 2 | `q5_vc_unicorn_strong_val_growth_rev` | Unicorn ($1B+ valuation) AND 75%+ `val_growth_3y` AND $100M+ revenue |
| 3 | `q5_vc_exceptional_val_growth` | 200%+ `val_growth_3y` AND $200M+ valuation (floor to filter noise from tiny companies) |
| 4 | `q5_vc_tier1_val_growth` | Backed by Tier 1 VC (Sequoia or a16z only, not Tier 2) AND $500M+ valuation AND 50%+ `val_growth_3y` |
| 5 | `q5_vc_exceptional_rev_growth` | 150%+ `rev_growth_3y` AND $100M+ revenue |

### Public Companies (2 paths)

| Path | Tag | Conditions (all must be true) |
|------|-----|-------------------------------|
| 1 | `q5_public_1b_rev_growth` | Revenue >= $1B AND 30%+ `rev_growth_3y` |
| 2 | `q5_public_5b_rev_growth` | Revenue >= $5B AND 20%+ `rev_growth_3y` |

### PE Companies (3 paths, stricter thresholds)

| Path | Tag | Conditions (all must be true) |
|------|-----|-------------------------------|
| 1 | `q5_pe_20b_rev_growth` | Revenue >= $20B AND 75%+ `rev_growth_3y` |
| 2 | `q5_pe_50b_rev_growth` | Revenue >= $50B AND 50%+ `rev_growth_3y` |
| 3 | `q5_pe_decacorn_rev_growth` | Decacorn ($10B+ valuation) AND 75%+ `rev_growth_3y` |

PE thresholds are intentionally higher than VC/Growth and Public because PE-backed companies are expected to show stronger fundamentals to earn Q5.

---

## Step 6: Q5 Validation and Guards

Three validation checks run in sequence. Each can demote a Q5 company to Q4. These guards prevent false positives from the promotion step.

### 6a. Stagnant Valuation Check

**Function:** `apply_stagnant_val_rev_check()`

**Trigger:** Company has $1B+ valuation AND < 10% 3-year valuation growth.

When triggered, the company must demonstrate exceptional revenue growth to retain Q5. The required growth threshold scales inversely with revenue - larger companies need less growth because their absolute revenue numbers are already significant.

| Revenue Level | Required `rev_growth_3y` to Retain Q5 |
|---------------|---------------------------------------|
| < $100M | 200%+ |
| $100M - $300M | 100%+ |
| $300M - $1B | 60%+ |
| $1B+ | 40%+ |
| No revenue data | Fails (demoted to Q4) |

Companies that fail this check are demoted from Q5 to Q4.

### 6b. Legacy Exclusion

**Function:** `apply_legacy_exclusion()`

Companies with `sub_quality = 'Legacy'` in the database cannot be Q5. Any Legacy company that was promoted to Q5 is demoted to Q4. This prevents historically declined companies from re-entering the highest tier.

### 6c. Revenue Declining Exclusion

**Function:** `apply_rev_declining_exclusion()`

Companies with negative 3-year revenue growth (`rev_growth_3y < 0`) cannot be Q5. Demoted to Q4.

---

## Step 7: Quality Drops

All drop rules reduce quality by exactly 1 level, with Q1 as the minimum floor. Multiple drops can stack across different rules, but each individual rule applies at most -1.

### 7a. Segment-Aware Stagnation Downgrade

**Function:** `apply_stagnation_downgrade()` with `stagnation_segment_aware=True`

Different segments are evaluated on different metrics and timescales, reflecting the natural pace of each segment.

| Segment | Stagnation Metric | Required Consecutive Years | Drop |
|---------|-------------------|---------------------------|------|
| VC | Valuation stagnation | 5+ years | -1 |
| Growth | Revenue stagnation | 3+ years | -1 |
| Public | Revenue stagnation | 5+ years | -1 |

Stagnation is defined as consecutive years with < 5% YoY growth in the relevant metric.

### 7b. VC Valuation Decline

**Function:** `apply_val_decline_downgrade()`

VC-segment companies with 30%+ 3-year valuation decline (`val_growth_3y <= -0.30`) receive -1 quality.

### 7c. Public Revenue Decline

**Function:** `apply_revenue_decline_downgrade()`

Public-segment companies with 20%+ 3-year revenue decline (`rev_growth_3y <= -0.20`) receive -1 quality.

### 7d. Growth Revenue Stagnation

**Function:** `apply_growth_rev_stagnation()`

Growth-segment companies with 3+ years of revenue stagnation receive -1 quality.

### 7e. PE Deal Decline

**Function:** `apply_pe_deal_decline()`

PE-segment companies with 50%+ 3-year deal activity decline receive -1 quality.

### 7f. Public/PE Segment Transition (Taken-Private Cap)

**Function:** `apply_segment_transition_rules()`

Companies that were Public and transitioned to PE (actual take-private transactions) with quality > Q3 are capped at Q3. This only applies to Public → PE transitions, not tech acquisitions (Public/Growth/VC → Acquired). Acquired companies use their pre-acquisition segment for Q5 path evaluation instead.

---

## Step 8: Acquisition Degradation

**Function:** `apply_acquisition_degradation()`

Q5 companies that are acquired (exit types: Acquired, Acq - P2P, Acq - Pending, Merger) drop to Q4 after 2 years post-acquisition. The 2-year grace period acknowledges that recently acquired companies may still be operating at peak performance, but acquisition typically leads to reduced innovation velocity.

---

## Step 9: Sub-Quality Assignment

**Function:** `apply_sub_quality_assignment()` in `engine/rules.py`

Runs after all quality scoring is complete. This step does not modify `calculated_qot` - it only assigns `calculated_sub_quality`.

### Eligibility

Only companies that achieved Q4+ in at least one year of their entire history are eligible for sub-quality designation. All other companies receive no sub-quality.

### Growth Percentile Computation

For each segment-year combination, the system computes the 75th percentile of:

- `rev_growth_3y` (3-year revenue growth)
- `val_growth_3y` (3-year valuation growth)

A company has "top-quartile growth" if its `rev_growth_3y` OR `val_growth_3y` is >= the 75th percentile for its segment in that year. This makes the threshold relative rather than absolute. A 20% growth rate might be top-quartile in a slow segment but not in a fast one.

### Decision Tree

For each eligible company-year, the system walks this decision tree:

```
Is calculated_qot == 5?
  YES --> Hot

Is calculated_qot == 4?
  --> Check Iconic Path A: Was Q5 within last 5 years AND top-25% growth?
      YES --> Iconic
  --> Check Iconic Path B: Was EVER Q5 AND is a category leader?
      (Category leader = 10+ years at Q4+, OR $1B+ revenue, OR market_score >= 900)
      YES --> Iconic
  --> Neither path met --> Incumbent

Is calculated_qot == 3?
  YES --> Incumbent

Is calculated_qot <= 2?
  YES --> Legacy
```

### Iconic Path Details

**Path A (Growth-based):** Requires BOTH recency (Q5 within last 5 years) and top-quartile growth. Catches companies that recently peaked and are still growing fast (e.g., Grafana Labs).

**Path B (Category Leadership):** Requires that the company was EVER Q5 (no recency requirement) and meets any one category leadership signal:
- **Longevity:** 10+ years at Q4+ in calculated history
- **Revenue scale:** $1B+ annual revenue
- **Market score:** CBI market_score >= 900 (private companies only)

Path B captures companies that defined their category years ago and still dominate even if growth has slowed (e.g., Box, Salesforce, ServiceNow).

### Long-Stagnant Incumbent to Legacy

Companies at Q3 that have been Incumbent for 5+ consecutive years are downgraded from Incumbent to Legacy. This rule only applies to Q3 companies. Q4 Incumbents remain Incumbent because they still hold Top quality and have not declined enough to warrant the Legacy label.

---

## VC Tier System

The VC tier system distinguishes between two levels of venture capital firm prestige. Both tiers are used in the no-mosaic fallback (Step 4), but only Tier 1 qualifies for Q5 promotion path 4.

### Tier 1 (2 firms)

Used for Q5 promotion path 4 (VC/Growth segment).

- Sequoia Capital
- Andreessen Horowitz (a16z)

### Tier 2 (21 firms)

Used alongside Tier 1 for the no-mosaic fallback VC backing point.

| | | |
|---|---|---|
| Accel | Benchmark | Kleiner Perkins |
| GV | Greylock Partners | Bessemer Venture Partners |
| Index Ventures | Lightspeed Venture Partners | NEA |
| Founders Fund | General Catalyst | Tiger Global Management |
| Insight Partners | Battery Ventures | Redpoint Ventures |
| Matrix Partners | Union Square Ventures | First Round Capital |
| Spark Capital | Thrive Capital | Coatue Management |

---

## Configuration

The system uses `SPEC_ALIGNED_CONFIG` defined in `utils/config.py`. This is the canonical configuration and differs from the legacy `DEFAULT_CONFIG`.

### Key Configuration Settings

| Setting | Value | Notes |
|---------|-------|-------|
| `baseline_strategy` | `"mosaic_only"` | Not `"quality_table"` |
| Mosaic thresholds | 850 / 650 / 500 | Not the legacy 900 / 750 / 650 |
| `upgrade_hot_to_5` | `False` | Hot is earned through promotion, not auto-assigned |
| `use_spec_pipeline` | `True` | Uses SPEC_RULE_PIPELINE |
| `q5_val_growth_min_valuation` | 200 | $200M floor on exceptional valuation growth path |
| All Q5 promotion paths | Enabled | Via `apply_q5_promotions` |
| All drop rules | Enabled | Stagnation, decline, PE deal decline |
| `recency_years` | 5 | How far back to look for Hot status when assigning Iconic |
| `growth_percentile` | 0.75 | 75th percentile threshold for top-quartile growth |
| `incumbent_to_legacy_years` | 5 | Consecutive Incumbent years at Q3 before Legacy |

### Disabled Rules

The following non-spec rules are disabled in `SPEC_ALIGNED_CONFIG`:

- `public_low_growth_downgrade`
- `public_large_rev_upgrade`
- `no_recent_funding_check`

---

## Testing Output

The system generates a single Excel workbook with 5 tabs, filtered to software companies only (`cbi_sector IN ('Internet', 'Software (non-internet/mobile)')`).

| Tab | Contents |
|-----|----------|
| Changes to Q5 | Companies promoted to or demoted from Q5 versus production |
| Sub-Quality Designations | All companies with any sub-quality, comparing DB values versus model output |
| Sub-Quality Transitions | Every company where designation changed, grouped by transition type |
| All Top Companies | All Q4+ companies with their model sub-quality |
| All Other Quality Changes | Non-Q5 quality changes versus production |

The headless test output generator is located at `scripts/generate_test_output.py`.

---

## File Structure

```
engine/
  rules.py              All scoring rule functions (26 legacy + 3 spec rules)
  scoring.py            Pipeline orchestrator (RULE_PIPELINE + SPEC_RULE_PIPELINE)
  compare.py            Production comparison logic
  writer.py             Database write-back
  spread.py             Temporal quality spreading

pipeline/
  segmentation.py       Company segmentation
  metrics.py            Temporal metrics computation
  build_metrics.py      Pipeline orchestrator

utils/
  config.py             DEFAULT_CONFIG, SPEC_ALIGNED_CONFIG, VC lists
  caching.py            DB connection + data caching
  data_loader.py        Data status helpers

components/             Streamlit UI components
scripts/
  generate_test_output.py   Headless test output generator
app.py                  Streamlit entry point
```

---

## Known Limitations and Future Work

### Public Company Valuation Gap

For most public companies, `val_growth_3y` is 0 because valuation data stops updating after IPO. Deal-based valuations are no longer recorded once a company is public. When quarterly market cap data becomes available, `val_growth_3y` will be populated from market cap instead of deal valuations, which will fix this gap and enable more accurate quality scoring for public companies.

### Manual Overrides

Step 15 (`apply_current_year_override`) supports manual "user" overrides but is currently disabled pending data cleanup. When re-enabled, user-provided quality scores will take precedence over all calculated values for the current year only.
