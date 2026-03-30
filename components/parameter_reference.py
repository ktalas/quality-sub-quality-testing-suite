"""
Parameter Reference: descriptions of every config variable and what each option means.
"""
import streamlit as st

PARAMETER_REFERENCE = {
    "How Scoring Works": {
        "description": (
            "Quality Over Time (QOT) assigns each company a quality score from **Q1** (lowest) to **Q5** (highest) "
            "for every year in their history. Scoring works as a **pipeline of rules** applied in order:\n\n"
            "1. **Set the baseline** — Choose a starting strategy (quality table, mosaic only, qot table, or blank slate). "
            "This determines each company-year's initial `calculated_qot`.\n"
            "2. **Sub-quality upgrades** — If enabled, Hot companies are set to Q5 and/or Iconic companies are set to Q5.\n"
            "3. **Mosaic floors** — Companies with high Mosaic scores get their quality raised to a minimum floor "
            "(e.g., Mosaic 900+ → at least Q4). Floors only raise, never lower.\n"
            "4. **Upgrade rules** — Revenue growth, valuation milestones, Tier 1 VC involvement, and exceptional growth "
            "rules can each **add +1** or **set a floor/target** for quality. These stack: a company could get +1 from "
            "revenue growth AND hit a unicorn floor in the same pass.\n"
            "5. **Downgrade rules** — Revenue decline, stagnation, segment transitions, and acquisition degradation "
            "can **subtract points** or **cap quality** at a level. Downgrades never push below Q1.\n"
            "6. **Q5 validation guards** — Final safety checks that can pull a company back from Q5 to Q4 if it "
            "doesn't demonstrate sufficient fundamentals (revenue, growth, recent funding).\n\n"
            "**Key principle: rules run in order, and later rules can override earlier ones.** A company might get "
            "upgraded to Q5 by a valuation rule, then immediately get pulled back to Q4 by a Q5 validation guard. "
            "The `last_rule_applied` column in the results shows which rule had the final say.\n\n"
            "**+1 rules vs target rules:** Some rules (revenue buckets, Tier 1 VC stages) add +1 to the current "
            "score (capped at Q5). Others (unicorn floor, decacorn floor, exceptional growth) set quality to a "
            "specific target. Downgrade rules subtract a fixed amount or cap at a maximum."
        ),
        "parameters": {},
    },
    "1. Base Quality": {
        "description": (
            "These rules establish the **starting quality score** for each company-year record. "
            "The baseline strategy controls how the initial score is set, then sub-quality and "
            "Mosaic score adjustments are applied on top. This is Phase 1 of the pipeline — "
            "everything else builds on whatever baseline you choose here."
        ),
        "parameters": {
            "baseline_strategy": {
                "label": "Baseline Strategy",
                "type": "string ('quality_table' | 'mosaic_only' | 'qot_table' | 'blank_slate')",
                "default": "quality_table",
                "description": (
                    "Controls how `calculated_qot` is initialized before any rules run.\n\n"
                    "- **quality_table** (default): Uses the static `companies.quality_score` (1-5) "
                    "and stretches it across all years. This is the simplest approach and the current "
                    "production baseline (~82.25% match). Every year for a company gets the same starting score.\n"
                    "- **mosaic_only**: Derives quality purely from the company's `mosaic_score` using the "
                    "configured thresholds (900+ → Q4, 750+ → Q3, 650+ → Q2, below → Q1). Since mosaic "
                    "scores are only available for private companies and cap at Q4, this baseline will never "
                    "produce Q5 on its own — Q5 must come from subsequent rules.\n"
                    "- **qot_table**: Uses actual production QOT values from the `qot` database table as the "
                    "starting point (matched by company_id + year). Falls back to `quality_score` for any "
                    "company-years not in the qot table. Useful for testing how your rules modify existing "
                    "production assignments.\n"
                    "- **blank_slate**: Every company-year starts at Q1. Quality is built entirely by "
                    "the subsequent rules. This reveals which rules are actually driving quality assignments "
                    "and how much they contribute. Expect the lowest match rate here."
                ),
            },
            "upgrade_hot_to_5": {
                "label": "Upgrade Hot → Q5",
                "type": "boolean",
                "default": True,
                "description": (
                    "Companies with `sub_quality = 'Hot'` are **set to Q5** (the highest quality). "
                    "'Hot' indicates the company is currently at the peak of its quality trajectory — "
                    "actively growing, well-funded, and considered a top-tier company right now. "
                    "This is a hard set (not +1), so regardless of baseline score, Hot = Q5."
                ),
            },
            "upgrade_iconic_to_5": {
                "label": "Upgrade Iconic → Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Companies with `sub_quality = 'Iconic'` are **set to Q5**. "
                    "'Iconic' companies achieved Q5/Hot status historically but may no longer be at peak. "
                    "Default is off because Iconic status alone doesn't mean a company is still top-quality — "
                    "it's a historical marker, not a current one."
                ),
            },
            "mosaic_900_threshold / mosaic_900_floor": {
                "label": "Mosaic top tier (threshold + floor)",
                "type": "float / integer (1-5)",
                "default": "900.0 / 4",
                "description": (
                    "Companies with Mosaic score >= 900 get their quality **raised to at least Q4**. "
                    "Mosaic is CB Insights' algorithmic scoring system evaluating private companies across "
                    "team, market, money, and momentum. A 900+ score is a very strong signal. "
                    "The floor only raises quality — a company already at Q5 stays at Q5. "
                    "The threshold and floor are independently configurable."
                ),
            },
            "mosaic_750_threshold / mosaic_750_floor": {
                "label": "Mosaic mid tier (threshold + floor)",
                "type": "float / integer (1-5)",
                "default": "750.0 / 3",
                "description": (
                    "Companies with Mosaic score >= 750 get quality raised to at least Q3. "
                    "Mid-range Mosaic — solid company but not exceptional."
                ),
            },
            "mosaic_650_threshold / mosaic_650_floor": {
                "label": "Mosaic low tier (threshold + floor)",
                "type": "float / integer (1-5)",
                "default": "650.0 / 2",
                "description": (
                    "Companies with Mosaic score >= 650 get quality raised to at least Q2. "
                    "Entry-level Mosaic tier — prevents these companies from sitting at Q1."
                ),
            },
        },
    },
    "2. Revenue Upgrades": {
        "description": (
            "Tiered revenue-based upgrades. Companies are grouped into **9 revenue buckets** by their "
            "current annual revenue. Each bucket independently checks whether the company's revenue growth "
            "meets a threshold — if so, quality gets **+1** (capped at Q5). Smaller companies require "
            "higher growth rates because early-stage growth should be faster.\n\n"
            "**How it works:** The system finds which bucket a company falls into based on its revenue, "
            "checks whether its growth (1-year or 3-year, per bucket config) meets the threshold, and if so, "
            "adds 1 point. A company can only match one bucket (its revenue determines which one). "
            "The +1 behavior means a Q2 company becomes Q3, a Q4 becomes Q5, etc."
        ),
        "parameters": {
            "enable_revenue_upgrade": {
                "label": "Enable revenue upgrades",
                "type": "boolean",
                "default": False,
                "description": (
                    "Master toggle for all tiered revenue upgrades. When disabled, no revenue bucket "
                    "rules run regardless of individual bucket settings."
                ),
            },
            "rev_upgrade_public_only": {
                "label": "Apply only to Public companies",
                "type": "boolean",
                "default": False,
                "description": (
                    "When checked, revenue bucket upgrades only apply to Public-segment companies. "
                    "Public company revenue data is audited and more reliable than private company estimates."
                ),
            },
            "rev_bucket_0_10m": {
                "label": "$0-10M bucket",
                "type": "dict {enabled, growth_period, growth_threshold}",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 3.00}",
                "description": (
                    "Companies with $0-10M revenue. Default threshold: 300% (3x) growth over 3 years. "
                    "Very early-stage — high growth bar because small-revenue companies should be growing fast. "
                    "Choose '1y' for growth_period to use 1-year growth instead of 3-year."
                ),
            },
            "rev_bucket_10m_30m": {
                "label": "$10-30M bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 2.50}",
                "description": "Companies with $10-30M revenue. Default: 250% growth. Early traction stage.",
            },
            "rev_bucket_30m_50m": {
                "label": "$30-50M bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 2.00}",
                "description": "Companies with $30-50M revenue. Default: 200% growth. Building scale.",
            },
            "rev_bucket_50m_200m": {
                "label": "$50-200M bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 1.50}",
                "description": "Companies with $50-200M revenue. Default: 150% growth. Growth stage.",
            },
            "rev_bucket_200m_500m": {
                "label": "$200-500M bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 1.00}",
                "description": "Companies with $200-500M revenue. Default: 100% growth. Scaling stage.",
            },
            "rev_bucket_500m_1b": {
                "label": "$500M-1B bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 0.60}",
                "description": "Companies with $500M-1B revenue. Default: 60% growth. Large-scale.",
            },
            "rev_bucket_1b_3b": {
                "label": "$1B-3B bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 0.40}",
                "description": "Companies with $1-3B revenue. Default: 40% growth. Mature growth.",
            },
            "rev_bucket_3b_10b": {
                "label": "$3B-10B bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 0.30}",
                "description": "Companies with $3-10B revenue. Default: 30% growth. Large enterprise.",
            },
            "rev_bucket_10b_plus": {
                "label": "$10B+ bucket",
                "type": "dict",
                "default": "{enabled: False, growth_period: '3y', growth_threshold: 0.20}",
                "description": (
                    "Companies with $10B+ revenue. Default: 20% growth. Mega-cap — even 20% growth "
                    "at this scale is exceptional and warrants a quality bump."
                ),
            },
            "public_rev_upgrade_enabled": {
                "label": "Enable public company revenue rule",
                "type": "boolean",
                "default": False,
                "description": (
                    "Separate revenue upgrade rule for public companies, independent of the bucket system. "
                    "Uses a flat minimum revenue + growth threshold. Useful for applying a single simple "
                    "check to public companies without configuring individual buckets."
                ),
            },
            "public_rev_upgrade_min_revenue": {
                "label": "Public min revenue (USD)",
                "type": "integer",
                "default": "5,000,000,000 ($5B)",
                "description": "Minimum revenue for the public company revenue upgrade.",
            },
            "public_rev_upgrade_growth_threshold": {
                "label": "Public min growth",
                "type": "float (ratio)",
                "default": 0.20,
                "description": (
                    "Minimum 3-year revenue growth for public companies. 0.20 = 20%. "
                    "Lower bar because large public companies grow slower but data is more reliable."
                ),
            },
        },
    },
    "3. Valuation Upgrades": {
        "description": (
            "Rules that upgrade quality based on company valuation milestones and growth. "
            "Unlike revenue upgrades which add +1, these rules **set quality to a specific target** "
            "(floor or target value). Valuations are stored in millions in the database."
        ),
        "parameters": {
            "enable_unicorn_upgrade": {
                "label": "Enable unicorn floor",
                "type": "boolean",
                "default": False,
                "description": (
                    "Sets a quality **floor** for unicorn companies ($1B+ valuation). "
                    "Reaching unicorn status is a strong market signal — investors valued the company at "
                    "$1B+, so it shouldn't sit below a minimum quality. Only raises quality, never lowers."
                ),
            },
            "unicorn_upgrade_quality_floor": {
                "label": "Unicorn quality floor",
                "type": "integer (1-5)",
                "default": 4,
                "description": "Minimum quality for unicorn companies. A floor — does not lower quality.",
            },
            "enable_decacorn_upgrade": {
                "label": "Enable decacorn floor",
                "type": "boolean",
                "default": False,
                "description": (
                    "Sets a quality **floor** for decacorn companies ($10B+ valuation). "
                    "An even stronger signal than unicorn status."
                ),
            },
            "decacorn_upgrade_quality_floor": {
                "label": "Decacorn quality floor",
                "type": "integer (1-5)",
                "default": 5,
                "description": "Minimum quality for decacorn companies.",
            },
            "enable_val_growth_upgrade": {
                "label": "Enable valuation growth upgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Upgrades companies with exceptionally strong 3-year valuation growth to a **target** quality. "
                    "This is a hard set, not +1. Captures companies whose valuations are growing rapidly."
                ),
            },
            "val_growth_threshold": {
                "label": "3yr growth threshold",
                "type": "float (ratio)",
                "default": 2.0,
                "description": (
                    "Minimum 3-year valuation growth ratio. 2.0 = 200% growth (valuation tripled). "
                    "Calculated as (current_val - val_3yr_ago) / val_3yr_ago."
                ),
            },
            "val_growth_upgrade_target": {
                "label": "Upgrade to quality",
                "type": "integer (1-5)",
                "default": 5,
                "description": "Target quality for companies meeting the valuation growth threshold.",
            },
            "require_revenue_validation": {
                "label": "Require revenue validation",
                "type": "boolean",
                "default": False,
                "description": (
                    "When enabled, valuation growth upgrades also require a minimum revenue. "
                    "Guards against upgrading companies with inflated valuations but no real revenue."
                ),
            },
            "val_upgrade_min_revenue": {
                "label": "Min revenue for validation (USD)",
                "type": "integer",
                "default": "500,000,000 ($500M)",
                "description": "Revenue floor when revenue validation is required for valuation upgrades.",
            },
        },
    },
    "4. Downgrade Rules": {
        "description": (
            "Rules that **reduce quality** for companies showing declining or stagnant metrics. "
            "Downgrades typically subtract a fixed number of points (e.g., -1) from the current quality. "
            "Quality never drops below Q1. These run after upgrades, so they can counteract upgrades "
            "that may have been too generous."
        ),
        "parameters": {
            "enable_revenue_decline_downgrade": {
                "label": "Enable revenue decline downgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Downgrades companies with significant revenue declines by **-1 quality point**. "
                    "Only applies to specified segments (e.g., Public) where revenue data is reliable."
                ),
            },
            "rev_decline_threshold": {
                "label": "Revenue decline threshold",
                "type": "float (negative ratio)",
                "default": -0.20,
                "description": (
                    "3-year revenue growth below which the downgrade triggers. "
                    "-0.20 = revenue dropped 20%+ over 3 years."
                ),
            },
            "rev_decline_segments": {
                "label": "Apply to segments",
                "type": "list of strings",
                "default": '["Public"]',
                "description": (
                    "Which segments this downgrade applies to. Options: VC, Growth, Public, PE, Acquired, Other."
                ),
            },
            "enable_stagnation_downgrade": {
                "label": "Enable stagnation downgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Downgrades companies with multi-year stagnation in revenue **or** valuation "
                    "by a configurable amount. Targets companies that have plateaued."
                ),
            },
            "rev_stagnation_years_threshold": {
                "label": "Revenue stagnation years",
                "type": "integer",
                "default": 5,
                "description": "Consecutive years of <5% revenue growth required to trigger.",
            },
            "val_stagnation_years_threshold": {
                "label": "Valuation stagnation years",
                "type": "integer",
                "default": 5,
                "description": "Consecutive years of <5% valuation growth required to trigger.",
            },
            "stagnation_downgrade_amount": {
                "label": "Downgrade amount",
                "type": "integer",
                "default": 1,
                "description": "Quality levels to subtract. 1 = Q4 → Q3, 2 = Q4 → Q2, etc.",
            },
        },
    },
    "5. Segment Rules": {
        "description": (
            "Rules triggered by changes in a company's **segment classification** (VC, Growth, Public, "
            "PE, Acquired, Other). These handle transitions between segments — e.g., a public company "
            "being taken private. Segments are determined by deal history."
        ),
        "parameters": {
            "enable_public_to_pe_downgrade": {
                "label": "Downgrade on Public → PE transition",
                "type": "boolean",
                "default": False,
                "description": (
                    "When a public company transitions to PE (taken private via buyout), **subtract** quality "
                    "points. Going private often signals reduced growth expectations."
                ),
            },
            "public_to_pe_min_quality": {
                "label": "Min quality to trigger",
                "type": "integer (1-5)",
                "default": 4,
                "description": "Only downgrades companies at or above this quality level.",
            },
            "public_to_pe_downgrade_amount": {
                "label": "Downgrade amount",
                "type": "integer",
                "default": 1,
                "description": "Quality levels to subtract on Public → PE transition.",
            },
            "enable_pe_deal_decline_downgrade": {
                "label": "Downgrade PE on deal activity decline",
                "type": "boolean",
                "default": False,
                "description": (
                    "Downgrades PE companies whose 3-year deal activity trend is declining. "
                    "Falling deal activity in PE may indicate wind-down."
                ),
            },
            "pe_deal_decline_threshold": {
                "label": "Deal decline threshold",
                "type": "float (negative ratio)",
                "default": -0.50,
                "description": "-0.50 = deal count dropped 50%+ over 3 years.",
            },
            "enable_taken_private_cap": {
                "label": "Cap quality for taken-private companies",
                "type": "boolean",
                "default": True,
                "description": (
                    "Hard **cap at Q3** for any company transitioning from Public to PE. "
                    "More aggressive than the standard downgrade — directly caps quality regardless "
                    "of what other rules set."
                ),
            },
        },
    },
    "6. Acquisition Rules": {
        "description": (
            "Rules governing how quality degrades after a company is **acquired**. Acquired companies "
            "maintain quality for a grace period, after which quality drops to a target level. "
            "This reflects the loss of independent growth trajectory post-acquisition."
        ),
        "parameters": {
            "enable_acquisition_degradation": {
                "label": "Enable acquisition quality degradation",
                "type": "boolean",
                "default": True,
                "description": (
                    "After a company is acquired (Acquired, Acq - P2P, Merger, etc.), its quality is "
                    "**capped at a target** after a delay. Only lowers quality — companies already below "
                    "the target are unaffected."
                ),
            },
            "acquisition_degradation_delay": {
                "label": "Years before degradation",
                "type": "integer",
                "default": 2,
                "description": (
                    "Grace period: years after acquisition before the quality cap kicks in. "
                    "Accounts for post-acquisition momentum."
                ),
            },
            "acquisition_degradation_target": {
                "label": "Degrade to quality",
                "type": "integer (1-5)",
                "default": 4,
                "description": "Quality cap applied after the delay. Only lowers, never raises.",
            },
        },
    },
    "7. Tier 1 VC Rules": {
        "description": (
            "Rules that upgrade companies backed by **top-tier venture capital firms**. The premise: "
            "Tier 1 VCs (Sequoia, a16z, Accel, Benchmark, etc.) have strong track records of picking "
            "winners, so their involvement is a quality signal.\n\n"
            "**How it works:** You define a list of Tier 1 VC firms and select which funding stages "
            "qualify for the upgrade. When a company has a Tier 1 VC on its cap table AND has raised "
            "a round at one of the enabled stages, it gets **+1 quality** (capped at Q5). "
            "The VC list is fully editable — add or remove firms as needed.\n\n"
            "**Example:** If you enable 'Series A' and 'Series B', a company that raised a Series A "
            "from Sequoia would get +1, but a company that only has Sequoia on a Seed round would not "
            "(unless 'Seed' is also enabled). The upgrade applies per company-year based on the funding "
            "rounds that occurred in that year."
        ),
        "parameters": {
            "enable_tier1_vc_upgrade": {
                "label": "Enable Tier 1 VC upgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Master toggle. When enabled, companies with Tier 1 VC involvement at selected "
                    "funding stages get +1 quality."
                ),
            },
            "tier1_vc_list": {
                "label": "Tier 1 VC firms",
                "type": "list of strings (or null for defaults)",
                "default": "null (uses 23 default firms)",
                "description": (
                    "The list of VC firms considered 'Tier 1'. Default includes 23 firms: "
                    "Sequoia Capital, Andreessen Horowitz, Accel, Benchmark, Kleiner Perkins, GV, "
                    "Greylock Partners, Bessemer Venture Partners, Index Ventures, Lightspeed Venture Partners, "
                    "NEA, Founders Fund, General Catalyst, Tiger Global Management, Insight Partners, "
                    "Battery Ventures, Redpoint Ventures, Matrix Partners, Union Square Ventures, "
                    "First Round Capital, Spark Capital, Thrive Capital, Coatue Management.\n\n"
                    "Set to `null` to use the defaults. Provide a list to override — firms you add will be "
                    "highlighted in the UI, and removed firms are shown as well."
                ),
            },
            "tier1_vc_stage_seed": {
                "label": "Seed stage",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality when a Tier 1 VC participated in a **Seed round** "
                    "(Angel, Pre-Seed, Seed, and variants). Very early — Tier 1 involvement at this stage "
                    "is a strong signal of potential but the company is still unproven."
                ),
            },
            "tier1_vc_stage_series_a": {
                "label": "Series A stage",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality for Tier 1 VC participation in **Series A** rounds. "
                    "Series A is typically the first institutional round — T1 VC involvement here "
                    "means the company passed rigorous due diligence."
                ),
            },
            "tier1_vc_stage_series_b": {
                "label": "Series B stage",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality for Tier 1 VC in **Series B** rounds. "
                    "The company has product-market fit and is scaling."
                ),
            },
            "tier1_vc_stage_series_c": {
                "label": "Series C stage",
                "type": "boolean",
                "default": False,
                "description": "Add +1 quality for Tier 1 VC in **Series C** rounds. Growth acceleration.",
            },
            "tier1_vc_stage_series_d": {
                "label": "Series D stage",
                "type": "boolean",
                "default": False,
                "description": "Add +1 quality for Tier 1 VC in **Series D** rounds. Late-stage growth.",
            },
            "tier1_vc_stage_late": {
                "label": "Late Stage (Series E+)",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality for Tier 1 VC in **Series E through K** rounds. "
                    "Very late stage — the company is likely pre-IPO or at scale."
                ),
            },
            "tier1_vc_stage_growth_equity": {
                "label": "Growth Equity stage",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality for Tier 1 VC in **Growth Equity** rounds. "
                    "These are typically larger investments in more mature companies."
                ),
            },
            "tier1_vc_stage_pe": {
                "label": "PE stage",
                "type": "boolean",
                "default": False,
                "description": (
                    "Add +1 quality for Tier 1 VC in **Private Equity** rounds "
                    "(including leveraged buyouts and management buyouts)."
                ),
            },
        },
    },
    "8. Advanced Rules": {
        "description": (
            "Additional rules covering edge cases, segment-specific logic, and guardrails. "
            "These handle nuanced scenarios like exceptional growth paths to Q5, PE-specific rules, "
            "and penalties for legacy/stagnant companies. Most are **disabled by default** — "
            "enable them to fine-tune scoring for specific company types."
        ),
        "parameters": {
            "enable_exceptional_val_growth": {
                "label": "Exceptional valuation growth → Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Non-PE companies with 3-year valuation growth above the threshold get **set to Q5**. "
                    "PE is excluded because PE valuations are buyout-driven. This is a target set, not +1."
                ),
            },
            "exceptional_val_growth_threshold": {
                "label": "3yr growth threshold",
                "type": "float (ratio)",
                "default": 2.0,
                "description": "2.0 = valuation tripled (200% growth).",
            },
            "enable_pe_hot_rules": {
                "label": "PE-specific Q5 rules",
                "type": "boolean",
                "default": False,
                "description": (
                    "Two-tier system for PE companies to reach Q5 (since they're excluded from general "
                    "exceptional growth). Requires very high revenue + strong revenue growth. "
                    "High tier: $50B+ rev and 50%+ growth. Lower tier: $20B+ rev and 75%+ growth."
                ),
            },
            "pe_hot_rev_threshold_high / pe_hot_growth_threshold_high": {
                "label": "High-tier PE rule",
                "type": "integer (USD) / float (ratio)",
                "default": "$50B / 0.50",
                "description": "Revenue and 3-year revenue growth for the high-tier PE Q5 rule.",
            },
            "pe_hot_rev_threshold_low / pe_hot_growth_threshold_low": {
                "label": "Lower-tier PE rule",
                "type": "integer (USD) / float (ratio)",
                "default": "$20B / 0.75",
                "description": (
                    "Revenue and growth for the lower-tier PE Q5 rule. "
                    "Higher growth bar compensates for lower revenue threshold."
                ),
            },
            "enable_rev_growth_upgrade": {
                "label": "Exceptional revenue growth → Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Companies with min revenue + exceptional 3-year revenue growth get **set to Q5**. "
                    "Catches companies with explosive revenue that may not have massive valuations yet."
                ),
            },
            "rev_growth_upgrade_min_revenue / rev_growth_upgrade_threshold": {
                "label": "Rev growth rule parameters",
                "type": "integer (USD) / float (ratio)",
                "default": "$100M / 1.50",
                "description": "Min revenue and 3-year growth (1.50 = 150% = revenue 2.5x).",
            },
            "enable_legacy_exclusion": {
                "label": "Legacy companies cannot be Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Prevents Legacy sub_quality companies from reaching Q5. If other rules would set "
                    "a Legacy company to Q5, it gets **capped at Q4**. Soft guard."
                ),
            },
            "enable_legacy_penalty": {
                "label": "Cap legacy company quality",
                "type": "boolean",
                "default": False,
                "description": (
                    "Hard quality **cap** for Legacy companies at a configurable maximum (default Q3). "
                    "More aggressive than legacy exclusion."
                ),
            },
            "legacy_penalty_max_quality": {
                "label": "Max quality for legacy",
                "type": "integer (1-5)",
                "default": 3,
                "description": "Maximum quality Legacy companies can have when the penalty is active.",
            },
            "enable_val_decline_downgrade": {
                "label": "VC valuation decline downgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Downgrades VC-segment companies with 3-year valuation decline above threshold by **-1**. "
                    "Valuation declines in VC are a strong negative signal."
                ),
            },
            "val_decline_threshold": {
                "label": "Decline threshold",
                "type": "float (negative ratio)",
                "default": -0.30,
                "description": "-0.30 = valuation dropped 30%+ over 3 years.",
            },
            "enable_growth_rev_stagnation": {
                "label": "Growth segment: revenue stagnation downgrade",
                "type": "boolean",
                "default": False,
                "description": (
                    "Downgrades Growth-segment companies with multi-year flat revenue by **-1**. "
                    "Growth companies are expected to grow — stagnation is a red flag."
                ),
            },
            "growth_rev_stagnation_years": {
                "label": "Years of stagnation",
                "type": "integer",
                "default": 3,
                "description": "Consecutive years of flat revenue before downgrade.",
            },
            "enable_stagnant_val_rev_check": {
                "label": "Stagnant valuation requires revenue growth for Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Q5 companies with $1B+ valuations but <10% valuation growth must pass a tiered "
                    "revenue growth check to stay at Q5. Uses revenue-based tiers: sub-$100M needs 200%+, "
                    "$100-300M needs 100%+, $300M-1B needs 60%+, $1B+ needs 40%+. "
                    "Failing companies get **capped at Q4**."
                ),
            },
            "stagnant_val_threshold": {
                "label": "Valuation growth below this = stagnant",
                "type": "float (ratio)",
                "default": 0.10,
                "description": "0.10 = 10%. Only Q5 companies with stagnant valuations are checked.",
            },
            "enable_no_recent_funding_check": {
                "label": "Higher bar for companies with no recent funding",
                "type": "boolean",
                "default": False,
                "description": (
                    "Q5 companies with no deals since the cutoff year face **higher** revenue growth "
                    "thresholds than the stagnant valuation check (300%/150%/100%/70% by tier). "
                    "Companies without recent funding are less market-validated."
                ),
            },
            "no_recent_funding_cutoff_year": {
                "label": "No deals since year",
                "type": "integer (year)",
                "default": 2022,
                "description": "Companies with no funding rounds since this year face the higher bar.",
            },
        },
    },
    "9. Q5 Validation Guards": {
        "description": (
            "Final safety checks that run **after all upgrades and downgrades**. These can pull a "
            "company back from Q5 to Q4 if it doesn't meet stricter validation criteria. "
            "Think of these as the last line of defense against inflated Q5 scores — even if "
            "everything else says Q5, these guards can override that."
        ),
        "parameters": {
            "enable_rev_declining_exclusion": {
                "label": "Revenue declining companies cannot be Q5",
                "type": "boolean",
                "default": False,
                "description": (
                    "Any Q5 company with negative 3-year revenue growth gets **downgraded to Q4**. "
                    "Simple rule: if revenue is shrinking, the company doesn't deserve top quality."
                ),
            },
            "enable_decacorn_revenue_validation": {
                "label": "Decacorn revenue validation",
                "type": "boolean",
                "default": False,
                "description": (
                    "Requires $10B+ valuation Q5 companies to demonstrate revenue fundamentals. "
                    "Being worth $10B+ alone is not enough. PE and non-PE decacorns have different "
                    "validation paths. Failing companies get **capped at Q4**."
                ),
            },
            "decacorn_pe_rev_growth_threshold": {
                "label": "PE decacorn required revenue growth",
                "type": "float (ratio)",
                "default": 0.75,
                "description": "PE decacorns need 75%+ 3-year revenue growth to keep Q5.",
            },
            "decacorn_nonpe_val_growth_threshold": {
                "label": "Non-PE decacorn valuation growth threshold",
                "type": "float (ratio)",
                "default": 0.30,
                "description": (
                    "Non-PE decacorns can validate via valuation growth (30%+) AND minimum revenue. "
                    "Alternative to revenue growth path."
                ),
            },
            "decacorn_nonpe_rev_growth_threshold": {
                "label": "Non-PE decacorn revenue growth threshold",
                "type": "float (ratio)",
                "default": 0.30,
                "description": "Alternative path: 30%+ revenue growth AND minimum revenue.",
            },
            "decacorn_min_revenue": {
                "label": "Min revenue for decacorn validation (USD)",
                "type": "integer",
                "default": "500,000,000 ($500M)",
                "description": "Revenue floor for both non-PE decacorn validation paths.",
            },
            "enable_unicorn_growth_validation": {
                "label": "Unicorn growth validation",
                "type": "boolean",
                "default": False,
                "description": (
                    "Requires unicorn ($1B-$10B) Q5 companies to show strong valuation growth + "
                    "minimum revenue to keep Q5. Failing companies get **capped at Q4**."
                ),
            },
            "unicorn_val_growth_threshold": {
                "label": "Unicorn valuation growth threshold",
                "type": "float (ratio)",
                "default": 0.75,
                "description": "75%+ 3-year valuation growth required.",
            },
            "unicorn_min_revenue": {
                "label": "Unicorn min revenue (USD)",
                "type": "integer",
                "default": "100,000,000 ($100M)",
                "description": "Revenue floor for unicorn Q5 validation.",
            },
        },
    },
    "10. Public Company Fine-Tuning": {
        "description": (
            "Rules that apply specifically to **public companies without a sub_quality** designation "
            "(not Hot, Iconic, or Legacy). These fine-tune quality for the large number of public "
            "companies that fall outside the sub_quality system. Both rules are **enabled by default** "
            "as they come from the baseline QOT calculator."
        ),
        "parameters": {
            "enable_public_low_growth_downgrade": {
                "label": "Downgrade low-growth public companies",
                "type": "boolean",
                "default": True,
                "description": (
                    "Public companies (no sub_quality) with revenue growth below threshold and quality "
                    "at or above min_quality get **set to the target** quality. Excludes the most recent "
                    "year (potentially incomplete data). Targets public companies coasting on high scores "
                    "despite sluggish growth."
                ),
            },
            "public_low_growth_threshold": {
                "label": "Growth threshold",
                "type": "float (ratio)",
                "default": 0.05,
                "description": "0.05 = 5%. Companies growing less than 5% over 3 years are low-growth.",
            },
            "public_low_growth_min_quality": {
                "label": "Min quality to trigger",
                "type": "integer (1-5)",
                "default": 4,
                "description": "Only downgrades public companies at or above this level.",
            },
            "public_low_growth_target": {
                "label": "Downgrade to",
                "type": "integer (1-5)",
                "default": 3,
                "description": "Quality level low-growth public companies get set to.",
            },
            "enable_public_large_rev_upgrade": {
                "label": "Upgrade large-revenue Q1 public companies",
                "type": "boolean",
                "default": True,
                "description": (
                    "Public companies (no sub_quality) with revenue above threshold and Q1 get "
                    "**upgraded to Q2**. Having $1B+ revenue is a signal they shouldn't sit at Q1."
                ),
            },
            "public_large_rev_threshold": {
                "label": "Min revenue (USD)",
                "type": "integer",
                "default": "1,000,000,000 ($1B)",
                "description": "Revenue above which a Q1 public company gets bumped to Q2.",
            },
        },
    },
}


def render_parameter_reference():
    """Render the full parameter reference as an expandable guide."""
    st.header("Parameter Reference")
    st.caption(
        "A complete guide to every configuration variable — what it does, what values it accepts, "
        "and how they combine to produce the final quality score."
    )

    for category, info in PARAMETER_REFERENCE.items():
        st.subheader(category)
        st.markdown(info["description"])

        for key, param in info["parameters"].items():
            with st.expander(f"**{param['label']}** (`{key}`)"):
                cols = st.columns([3, 1])
                with cols[0]:
                    st.markdown(param["description"])
                with cols[1]:
                    st.markdown(f"**Type:** {param['type']}")
                    st.markdown(f"**Default:** `{param['default']}`")

        st.divider()
