from pathlib import Path

import pytest

from mobilityops.config import ConfigError, Settings


def test_defaults_are_safe_sample_mode() -> None:
    s = Settings.from_env({})
    assert s.mode == "sample"
    assert s.log_level == "INFO"
    assert s.anthropic_api_key is None
    assert not s.llm_configured


def test_modes_use_separate_directories() -> None:
    a = Settings.from_env({"MOBILITYOPS_DATA_DIR": "/tmp/x", "MOBILITYOPS_MODE": "sample"})
    b = Settings.from_env({"MOBILITYOPS_DATA_DIR": "/tmp/x", "MOBILITYOPS_MODE": "real"})
    assert a.processed_dir != b.processed_dir
    assert a.raw_dir != b.raw_dir
    assert a.db_path != b.db_path  # synthetic and real results can never share a database


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"MOBILITYOPS_MODE": "production"}, "MOBILITYOPS_MODE"),
        ({"MOBILITYOPS_LOG_LEVEL": "LOUD"}, "MOBILITYOPS_LOG_LEVEL"),
    ],
)
def test_invalid_values_fail_clearly(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        Settings.from_env(env)


def test_llm_needs_both_key_and_model() -> None:
    assert not Settings.from_env({"ANTHROPIC_API_KEY": "k"}).llm_configured
    assert Settings.from_env(
        {"ANTHROPIC_API_KEY": "k", "MOBILITYOPS_LLM_MODEL": "m"}
    ).llm_configured
    assert not Settings.from_env({"ANTHROPIC_API_KEY": "  "}).llm_configured


def test_secret_never_appears_in_repr() -> None:
    s = Settings.from_env({"ANTHROPIC_API_KEY": "sk-super-secret-value"})
    assert "sk-super-secret-value" not in repr(s)
    assert "sk-super-secret-value" not in str(s)


def test_ensure_dirs_creates_layout(tmp_path: Path) -> None:
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(tmp_path / "d")})
    s.ensure_dirs()
    assert s.raw_dir.is_dir() and s.processed_dir.is_dir() and s.manifests_dir.is_dir()


def test_threads_setting_defaults_to_all_cores_and_rejects_nonsense() -> None:
    assert Settings.from_env({}).threads == 0
    assert Settings.from_env({"MOBILITYOPS_THREADS": "4"}).threads == 4
    for bad in ("-1", "many", "999", "1.5"):
        with pytest.raises(ConfigError, match="MOBILITYOPS_THREADS"):
            Settings.from_env({"MOBILITYOPS_THREADS": bad})


def test_thread_cap_reaches_the_model_parameters_unless_overridden() -> None:
    from mobilityops.forecasting.evaluate import EvalConfig, _with_threads

    capped = Settings.from_env({"MOBILITYOPS_THREADS": "3"})
    assert _with_threads(EvalConfig(), capped).params["num_threads"] == 3
    assert _with_threads(EvalConfig(params={"num_threads": 1}), capped).params["num_threads"] == 1
    assert "num_threads" not in _with_threads(EvalConfig(), Settings.from_env({})).params


def test_live_settings_have_safe_defaults_and_are_validated() -> None:
    s = Settings.from_env({})
    assert (s.live_seconds_per_hour, s.live_feeds, s.live_max_streams) == (2.0, True, 32)
    t = Settings.from_env(
        {
            "MOBILITYOPS_LIVE_SECONDS_PER_HOUR": "0.5",
            "MOBILITYOPS_LIVE_FEEDS": "false",
            "MOBILITYOPS_LIVE_MAX_STREAMS": "4",
        }
    )
    assert (t.live_seconds_per_hour, t.live_feeds, t.live_max_streams) == (0.5, False, 4)


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"MOBILITYOPS_LIVE_SECONDS_PER_HOUR": "0"}, "SECONDS_PER_HOUR"),
        ({"MOBILITYOPS_LIVE_SECONDS_PER_HOUR": "fast"}, "SECONDS_PER_HOUR"),
        ({"MOBILITYOPS_LIVE_SECONDS_PER_HOUR": "99999"}, "SECONDS_PER_HOUR"),
        ({"MOBILITYOPS_LIVE_FEEDS": "maybe"}, "LIVE_FEEDS"),
        ({"MOBILITYOPS_LIVE_MAX_STREAMS": "-1"}, "LIVE_MAX_STREAMS"),
    ],
)
def test_invalid_live_settings_fail_clearly(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        Settings.from_env(env)
