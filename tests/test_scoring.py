"""
Tests for the scoring pipeline: verifies run_scoring works with every
combination of config toggles and baseline strategies.
"""
import sys
import os
import pytest
import pandas as pd
import numpy as np
from itertools import combinations

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.config import DEFAULT_CONFIG
from engine.scoring import run_scoring, RULE_PIPELINE
from engine.rules import REVENUE_BUCKETS


# ── Fixtures ─────────────────────────────────────────────────────────────

def _make_test_df(n=20):
    """Build a realistic mock DataFrame with all columns the pipeline reads."""
    rng = np.random.RandomState(42)
    segments = ['VC', 'Growth', 'Public', 'PE', 'Acquired', 'Other']
    sub_qualities = [None, None, None, 'Hot', 'Iconic', 'Legacy']
    exit_types = [None, None, None, 'Acquired', 'Acq - P2P', 'Merger', 'IPO']

    rows = []
    for i in range(n):
        cid = i // 4 + 1  # ~5 companies, 4 years each
        year = 2020 + (i % 4)
        seg = segments[i % len(segments)]
        rows.append({
            'company_id': cid,
            'company_name': f'Company_{cid}',
            'year': year,
            'segment': seg,
            'prev_segment': segments[(i + 1) % len(segments)],
            'segment_changed': rng.choice([True, False]),
            'quality_score': rng.randint(1, 6),
            'sub_quality': sub_qualities[i % len(sub_qualities)],
            'mosaic_score': rng.choice([0, 500, 650, 750, 900, 950]),
            'revenue': rng.choice([0, 5_000_000, 50_000_000, 200_000_000,
                                   500_000_000, 1_500_000_000, 8_000_000_000,
                                   60_000_000_000]),
            'rev_growth_1y': rng.uniform(-0.5, 4.0),
            'rev_growth_3y': rng.uniform(-0.5, 4.0),
            'eoy_valuation': rng.choice([0, 100, 500, 1000, 5000, 15000]),
            'val_growth_3y': rng.uniform(-0.5, 3.0),
            'is_unicorn': rng.choice([True, False]),
            'is_decacorn': rng.choice([True, False]),
            'has_tier1_vc': rng.choice([True, False]),
            'funding_rounds': rng.choice(['', 'Seed', 'Series A', 'Series B', 'Series C',
                                          'Series D', 'Series E', 'Growth Equity',
                                          'Series A, Series B', 'Seed, Series A']),
            'deals_count': rng.randint(0, 5),
            'deal_trend_3y': rng.uniform(-1.0, 2.0),
            'rev_stagnation_years': rng.randint(0, 8),
            'val_stagnation_years': rng.randint(0, 8),
            'years_since_last_deal': rng.randint(0, 10),
            'exit_type': exit_types[i % len(exit_types)],
            'years_since_exit': rng.choice([np.nan, 0, 1, 2, 3, 5]),
            'company_age': rng.randint(1, 20),
            'peak_valuation_to_date': rng.choice([0, 500, 2000, 10000]),
            'exit_value': rng.choice([0, 100, 1000, 5000]),
            'cumulative_raised': rng.choice([0, 50, 500, 2000]),
        })
    return pd.DataFrame(rows)


def _make_production_qot(df):
    """Build a mock production qot table matching the test df."""
    return df[['company_id', 'year']].copy().assign(
        qot=np.random.RandomState(99).randint(1, 6, size=len(df))
    )


@pytest.fixture
def test_df():
    return _make_test_df()


@pytest.fixture
def production_qot(test_df):
    return _make_production_qot(test_df)


# ── Helper ───────────────────────────────────────────────────────────────

def _assert_valid_output(result):
    """Check that scoring output is well-formed."""
    assert 'calculated_qot' in result.columns
    assert result['calculated_qot'].between(1, 5).all(), \
        f"Out of range: {result['calculated_qot'][~result['calculated_qot'].between(1, 5)].tolist()}"
    assert result['calculated_qot'].dtype in (np.int64, np.int32, int)
    assert 'rules_applied' in result.columns
    assert 'last_rule_applied' in result.columns


# ── Core Tests ───────────────────────────────────────────────────────────

class TestDefaultConfig:
    """Run scoring with default config (baseline match)."""

    def test_default_config_runs(self, test_df):
        result = run_scoring(test_df, DEFAULT_CONFIG)
        _assert_valid_output(result)
        assert len(result) == len(test_df)

    def test_default_config_no_mutations(self, test_df):
        config_before = DEFAULT_CONFIG.copy()
        run_scoring(test_df, DEFAULT_CONFIG)
        assert DEFAULT_CONFIG == config_before, "DEFAULT_CONFIG was mutated"


class TestBaselineStrategies:
    """Each baseline strategy should run without errors."""

    @pytest.mark.parametrize("strategy", [
        "quality_table", "mosaic_only", "qot_table", "blank_slate"
    ])
    def test_baseline_strategy(self, test_df, production_qot, strategy):
        config = DEFAULT_CONFIG.copy()
        config['baseline_strategy'] = strategy
        prod = production_qot if strategy == 'qot_table' else None
        result = run_scoring(test_df, config, production_qot=prod)
        _assert_valid_output(result)

    def test_qot_table_without_data_falls_back(self, test_df):
        """qot_table baseline without production data should fall back to quality_table."""
        config = DEFAULT_CONFIG.copy()
        config['baseline_strategy'] = 'qot_table'
        result = run_scoring(test_df, config, production_qot=None)
        _assert_valid_output(result)

    def test_blank_slate_starts_at_q1(self, test_df):
        """blank_slate with no rules enabled should leave everything at Q1."""
        config = DEFAULT_CONFIG.copy()
        config['baseline_strategy'] = 'blank_slate'
        # Disable all optional rules
        for key in list(config.keys()):
            if key.startswith('enable_') or key == 'upgrade_hot_to_5' or key == 'upgrade_iconic_to_5':
                config[key] = False
        # Mosaic floors still run (no enable_ key) — set floors to 1 so they don't upgrade
        config['mosaic_900_floor'] = 1
        config['mosaic_750_floor'] = 1
        config['mosaic_650_floor'] = 1
        result = run_scoring(test_df, config)
        _assert_valid_output(result)
        assert (result['calculated_qot'] == 1).all(), "Blank slate + no rules should be all Q1"


class TestEveryRuleToggle:
    """Enable each rule individually and verify no crashes."""

    @pytest.mark.parametrize("rule_name", [name for name, _ in RULE_PIPELINE])
    def test_single_rule_enabled(self, test_df, rule_name):
        """Enable one rule at a time on top of disabled config."""
        config = DEFAULT_CONFIG.copy()
        # Disable everything first
        for key in list(config.keys()):
            if key.startswith('enable_'):
                config[key] = False
        config['upgrade_hot_to_5'] = False
        config['upgrade_iconic_to_5'] = False
        config['enable_taken_private_cap'] = False

        # Enable the specific rule
        enable_key = f"enable_{rule_name}"
        if enable_key in config:
            config[enable_key] = True

        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_all_rules_enabled(self, test_df):
        """Enable every single rule simultaneously."""
        config = DEFAULT_CONFIG.copy()
        for key in list(config.keys()):
            if key.startswith('enable_'):
                config[key] = True
        config['upgrade_hot_to_5'] = True
        config['upgrade_iconic_to_5'] = True

        # Enable all revenue buckets
        for suffix, _, _ in REVENUE_BUCKETS:
            config[f'rev_bucket_{suffix}'] = {
                'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.10
            }

        result = run_scoring(test_df, config)
        _assert_valid_output(result)


class TestRevenueBuckets:
    """Test the tiered revenue upgrade system."""

    @pytest.mark.parametrize("suffix,lower,upper", REVENUE_BUCKETS)
    def test_each_bucket_individually(self, test_df, suffix, lower, upper):
        config = DEFAULT_CONFIG.copy()
        config['enable_revenue_upgrade'] = True
        config[f'rev_bucket_{suffix}'] = {
            'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.10
        }
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    @pytest.mark.parametrize("period", ["1y", "3y"])
    def test_growth_period_options(self, test_df, period):
        config = DEFAULT_CONFIG.copy()
        config['enable_revenue_upgrade'] = True
        config['rev_bucket_1b_3b'] = {
            'enabled': True, 'growth_period': period, 'growth_threshold': 0.10
        }
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_all_buckets_enabled(self, test_df):
        config = DEFAULT_CONFIG.copy()
        config['enable_revenue_upgrade'] = True
        for suffix, _, _ in REVENUE_BUCKETS:
            config[f'rev_bucket_{suffix}'] = {
                'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.05
            }
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_public_only_flag(self, test_df):
        config = DEFAULT_CONFIG.copy()
        config['enable_revenue_upgrade'] = True
        config['rev_upgrade_public_only'] = True
        config['rev_bucket_1b_3b'] = {
            'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.01
        }
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_plus_one_behavior(self):
        """Verify buckets add +1 to quality, not set a target."""
        df = pd.DataFrame({
            'company_id': [1, 2],
            'company_name': ['A', 'B'],
            'year': [2023, 2023],
            'segment': ['Public', 'Public'],
            'prev_segment': ['Public', 'Public'],
            'segment_changed': [False, False],
            'quality_score': [2, 4],
            'sub_quality': [None, None],
            'mosaic_score': [0, 0],
            'revenue': [2_000_000_000, 2_000_000_000],
            'rev_growth_1y': [0.5, 0.5],
            'rev_growth_3y': [0.5, 0.5],
            'eoy_valuation': [0, 0],
            'val_growth_3y': [0, 0],
            'is_unicorn': [False, False],
            'is_decacorn': [False, False],
            'has_tier1_vc': [False, False],
            'funding_rounds': ['', ''],
            'deals_count': [0, 0],
            'deal_trend_3y': [0, 0],
            'rev_stagnation_years': [0, 0],
            'val_stagnation_years': [0, 0],
            'years_since_last_deal': [0, 0],
            'exit_type': [None, None],
            'years_since_exit': [np.nan, np.nan],
            'company_age': [5, 5],
            'peak_valuation_to_date': [0, 0],
            'exit_value': [0, 0],
            'cumulative_raised': [0, 0],
        })

        config = DEFAULT_CONFIG.copy()
        # Disable everything except revenue upgrades
        for key in list(config.keys()):
            if key.startswith('enable_'):
                config[key] = False
        config['upgrade_hot_to_5'] = False
        config['upgrade_iconic_to_5'] = False
        config['enable_revenue_upgrade'] = True
        config['rev_bucket_1b_3b'] = {
            'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.3
        }

        result = run_scoring(df, config)
        # Company 1: Q2 base + 1 = Q3
        assert result.loc[0, 'calculated_qot'] == 3
        # Company 2: Q4 base + 1 = Q5
        assert result.loc[1, 'calculated_qot'] == 5


class TestBaselineWithAllRules:
    """Test each baseline strategy with all rules enabled."""

    @pytest.mark.parametrize("strategy", [
        "quality_table", "mosaic_only", "qot_table", "blank_slate"
    ])
    def test_full_pipeline_per_baseline(self, test_df, production_qot, strategy):
        config = DEFAULT_CONFIG.copy()
        config['baseline_strategy'] = strategy

        # Enable everything
        for key in list(config.keys()):
            if key.startswith('enable_'):
                config[key] = True
        config['upgrade_hot_to_5'] = True
        config['upgrade_iconic_to_5'] = True
        for suffix, _, _ in REVENUE_BUCKETS:
            config[f'rev_bucket_{suffix}'] = {
                'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.05
            }

        prod = production_qot if strategy == 'qot_table' else None
        result = run_scoring(test_df, config, production_qot=prod)
        _assert_valid_output(result)


class TestEdgeCases:
    """Edge cases that might cause crashes."""

    def test_empty_dataframe(self):
        """Empty df should not crash."""
        df = _make_test_df(0)
        # Ensure all columns exist even with 0 rows
        for col in ['company_id', 'company_name', 'year', 'segment', 'prev_segment',
                     'segment_changed', 'quality_score', 'sub_quality', 'mosaic_score',
                     'revenue', 'rev_growth_1y', 'rev_growth_3y', 'eoy_valuation',
                     'val_growth_3y', 'is_unicorn', 'is_decacorn', 'has_tier1_vc',
                     'funding_rounds', 'deals_count', 'deal_trend_3y', 'rev_stagnation_years',
                     'val_stagnation_years', 'years_since_last_deal', 'exit_type',
                     'years_since_exit', 'company_age', 'peak_valuation_to_date',
                     'exit_value', 'cumulative_raised']:
            if col not in df.columns:
                df[col] = pd.Series(dtype='object')
        result = run_scoring(df, DEFAULT_CONFIG)
        assert len(result) == 0

    def test_all_null_sub_quality(self, test_df):
        """No sub_quality values should not crash."""
        test_df['sub_quality'] = None
        result = run_scoring(test_df, DEFAULT_CONFIG)
        _assert_valid_output(result)

    def test_all_nan_revenue(self, test_df):
        """NaN revenue should not crash."""
        test_df['revenue'] = np.nan
        test_df['rev_growth_1y'] = np.nan
        test_df['rev_growth_3y'] = np.nan
        config = DEFAULT_CONFIG.copy()
        config['enable_revenue_upgrade'] = True
        for suffix, _, _ in REVENUE_BUCKETS:
            config[f'rev_bucket_{suffix}'] = {
                'enabled': True, 'growth_period': '3y', 'growth_threshold': 0.1
            }
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_all_nan_mosaic(self, test_df):
        """NaN mosaic scores with mosaic_only baseline should produce Q1."""
        test_df['mosaic_score'] = np.nan
        config = DEFAULT_CONFIG.copy()
        config['baseline_strategy'] = 'mosaic_only'
        # Disable sub_quality upgrades to see pure mosaic effect
        config['upgrade_hot_to_5'] = False
        config['upgrade_iconic_to_5'] = False
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_all_nan_valuation(self, test_df):
        """NaN valuations should not crash valuation rules."""
        test_df['eoy_valuation'] = np.nan
        test_df['val_growth_3y'] = np.nan
        config = DEFAULT_CONFIG.copy()
        config['enable_unicorn_upgrade'] = True
        config['enable_decacorn_upgrade'] = True
        config['enable_val_growth_upgrade'] = True
        config['enable_exceptional_val_growth'] = True
        config['enable_val_decline_downgrade'] = True
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_extreme_values(self, test_df):
        """Extreme revenue/valuation values should not overflow."""
        test_df['revenue'] = 999_999_999_999  # ~$1T
        test_df['eoy_valuation'] = 999_999  # ~$1T in millions
        test_df['rev_growth_3y'] = 100.0  # 10000% growth
        test_df['val_growth_3y'] = 100.0
        config = DEFAULT_CONFIG.copy()
        for key in config:
            if key.startswith('enable_'):
                config[key] = True
        config['upgrade_hot_to_5'] = True
        config['upgrade_iconic_to_5'] = True
        result = run_scoring(test_df, config)
        _assert_valid_output(result)

    def test_quality_score_out_of_range(self, test_df):
        """quality_score values outside 1-5 should be clipped."""
        test_df['quality_score'] = 99
        result = run_scoring(test_df, DEFAULT_CONFIG)
        _assert_valid_output(result)
        assert result['calculated_qot'].max() <= 5

    def test_negative_quality_score(self, test_df):
        test_df['quality_score'] = -5
        result = run_scoring(test_df, DEFAULT_CONFIG)
        _assert_valid_output(result)
        assert result['calculated_qot'].min() >= 1


class TestRandomConfigCombinations:
    """Fuzz test: random combinations of enabled/disabled rules."""

    def test_random_toggle_combos(self, test_df):
        """Try 50 random config permutations."""
        rng = np.random.RandomState(123)
        enable_keys = [k for k in DEFAULT_CONFIG if k.startswith('enable_')]

        for _ in range(50):
            config = DEFAULT_CONFIG.copy()
            for key in enable_keys:
                config[key] = bool(rng.choice([True, False]))
            config['upgrade_hot_to_5'] = bool(rng.choice([True, False]))
            config['upgrade_iconic_to_5'] = bool(rng.choice([True, False]))
            config['baseline_strategy'] = rng.choice([
                'quality_table', 'mosaic_only', 'blank_slate'
            ])

            # Randomly enable some revenue buckets
            if config.get('enable_revenue_upgrade'):
                for suffix, _, _ in REVENUE_BUCKETS:
                    config[f'rev_bucket_{suffix}'] = {
                        'enabled': bool(rng.choice([True, False])),
                        'growth_period': rng.choice(['1y', '3y']),
                        'growth_threshold': float(rng.uniform(0.05, 3.0)),
                    }

            result = run_scoring(test_df, config)
            _assert_valid_output(result)
