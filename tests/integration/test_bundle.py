"""Demo-bundle provenance: the manifest, and the checks that stop code and data drifting apart."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mobilityops import bundle
from mobilityops.anomaly.run import run_anomaly_detection
from mobilityops.api.app import create_app
from mobilityops.cli import main as cli_main
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import run_evaluation, train_final

MODE = "sample"


@pytest.fixture(scope="module")
def bundle_root(built_sample, tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """A copy of the synthetic pipeline's output laid out the way a hosted bundle is: database,
    forecasts, registered model and anomaly report, under one root."""
    st, _ = built_sample
    run_evaluation(st, oracle_experiment=False)
    train_final(st)
    run_anomaly_detection(st, injection=False)
    root = tmp_path_factory.mktemp("bundle")
    shutil.copytree(st.data_dir / "processed" / MODE, root / "data" / "processed" / MODE)
    shutil.copytree(st.data_dir.parent / "artifacts" / MODE, root / "artifacts" / MODE)
    return root


@pytest.fixture()
def fresh(bundle_root: Path, tmp_path: Path) -> Path:
    """A private copy of the bundle, so a test may damage it."""
    dest = tmp_path / "b"
    shutil.copytree(bundle_root, dest)
    return dest


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name != bundle.MANIFEST_NAME)


def _write_manifest(root: Path) -> dict:
    manifest = bundle.build_manifest(root, MODE, _files(root))
    (root / bundle.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def _model_meta_path(root: Path) -> Path:
    arts = bundle.artifact_runs(root, MODE)
    return root / "artifacts" / MODE / "forecast" / "models" / arts["model_id"] / "meta.json"


# ---------------------------------------------------------------------- the schema the code expects
def test_core_schema_is_exactly_what_the_gold_builder_produces(built_sample) -> None:  # type: ignore[no-untyped-def]
    """If the gold layer changes, this fails until CORE_SCHEMA (and so the fingerprint) is updated,
    which is what makes old bundles fail loudly instead of quietly serving the wrong shape."""
    st, _ = built_sample
    built = bundle.db_schema(st.db_path)
    for table, cols in bundle.CORE_SCHEMA.items():
        assert table in built, table
        assert list(cols) == built[table], table


def test_schema_fingerprint_changes_with_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    before = bundle.schema_sha256()
    assert before == bundle.schema_sha256()  # stable
    zone = bundle.CORE_SCHEMA["dim_zone"]
    changed = {**bundle.CORE_SCHEMA, "dim_zone": (*zone, ("x", "INTEGER"))}
    monkeypatch.setattr(bundle, "CORE_SCHEMA", changed)
    assert bundle.schema_sha256() != before
    monkeypatch.setattr(bundle, "CORE_SCHEMA", bundle.CORE_SCHEMA)
    monkeypatch.setattr(bundle, "SCHEMA_VERSION", bundle.SCHEMA_VERSION + 1)
    assert bundle.schema_sha256() != before


# ---------------------------------------------------------------------------- a healthy bundle
def test_a_bundle_without_a_manifest_works_but_says_it_cannot_name_its_commit(
    bundle_root: Path,
) -> None:
    rep = bundle.check_bundle(bundle_root, MODE)
    assert rep.ok, rep.problems
    assert any(bundle.MANIFEST_NAME in w for w in rep.warnings)
    assert rep.info["model_id"] and rep.info["data_run_id"]


def test_the_manifest_records_commit_run_model_schema_and_every_file(fresh: Path) -> None:
    m = _write_manifest(fresh)
    assert m["manifest_version"] == bundle.MANIFEST_VERSION and m["kind"] == MODE
    assert m["schema_sha256"] == bundle.schema_sha256()
    assert m["schema_version"] == bundle.SCHEMA_VERSION
    run = bundle.latest_run(fresh / "data" / "processed" / MODE / "mobilityops.duckdb")
    assert m["data_run_id"] == run["run_id"] and m["data_built_by_commit"] == run["git_commit"]
    assert m["model_id"] and m["model_data_run_id"] == run["run_id"]
    assert m["consistent"] is True and m["inconsistencies"] == []
    listed = {f["path"] for f in m["files"]}
    assert listed == {str(p.relative_to(fresh)) for p in _files(fresh)}
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in m["files"])
    rep = bundle.check_bundle(fresh, MODE)
    assert rep.ok and rep.warnings == [], (rep.problems, rep.warnings)


def test_the_manifest_is_deterministic(fresh: Path) -> None:
    assert _write_manifest(fresh) == _write_manifest(fresh)


# ------------------------------------------------------------------------- what it must catch
def test_an_altered_or_missing_file_is_detected(fresh: Path) -> None:
    _write_manifest(fresh)
    victim = fresh / "artifacts" / MODE / "forecast" / "evaluation.json"
    victim.write_text(victim.read_text() + " ")
    rep = bundle.check_bundle(fresh, MODE)
    assert not rep.ok and any("evaluation.json does not match" in p for p in rep.problems)
    victim.unlink()
    problems = bundle.check_bundle(fresh, MODE).problems
    assert any("evaluation.json is listed in the manifest but missing" in p for p in problems)
    # hashing can be skipped for a quick structural check
    quick = bundle.check_bundle(fresh, MODE, verify_files=False).problems
    assert not any("missing" in p for p in quick)


def test_a_bundle_packed_for_a_different_schema_is_refused(
    fresh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_manifest(fresh)
    monkeypatch.setattr(bundle, "SCHEMA_VERSION", bundle.SCHEMA_VERSION + 1)
    rep = bundle.check_bundle(fresh, MODE)
    assert not rep.ok and any("packed for schema" in p for p in rep.problems)


def test_a_database_missing_a_column_the_code_reads_is_refused(
    fresh: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zone = bundle.CORE_SCHEMA["dim_zone"]
    extra = {**bundle.CORE_SCHEMA, "dim_zone": (*zone, ("new_col", "INTEGER"))}
    monkeypatch.setattr(bundle, "CORE_SCHEMA", extra)
    assert "dim_zone.new_col is missing" in bundle.check_bundle(fresh, MODE).problems
    wrong_type = {**bundle.CORE_SCHEMA, "dim_zone": (("location_id", "VARCHAR"),)}
    monkeypatch.setattr(bundle, "CORE_SCHEMA", wrong_type)
    assert any("location_id is BIGINT" in p for p in bundle.check_bundle(fresh, MODE).problems)


def test_a_model_trained_on_features_the_code_no_longer_computes_is_refused(fresh: Path) -> None:
    meta_path = _model_meta_path(fresh)
    meta = json.loads(meta_path.read_text())
    meta["features"] = [*meta["features"], "a_feature_from_the_future"]
    meta_path.write_text(json.dumps(meta))
    rep = bundle.check_bundle(fresh, MODE)
    assert not rep.ok and any("a_feature_from_the_future" in p for p in rep.problems)


def test_artifacts_made_from_a_different_data_run_are_flagged_and_not_packed_silently(
    fresh: Path,
) -> None:
    """The drift found in the New York bundle: the database was rebuilt after the model was made."""
    meta_path = _model_meta_path(fresh)
    meta = json.loads(meta_path.read_text())
    meta["data_run_id"] = "20200101T000000Z-deadbeef"
    meta_path.write_text(json.dumps(meta))
    rep = bundle.check_bundle(fresh, MODE)
    assert rep.ok  # it still works ...
    stale = "trained model was made from data run 20200101T000000Z-deadbeef"
    assert any(stale in w for w in rep.warnings)
    # ... but a manifest records the inconsistency
    m = bundle.build_manifest(fresh, MODE, _files(fresh))
    assert m["consistent"] is False and "20200101T000000Z-deadbeef" in m["inconsistencies"][0]


def test_a_manifest_for_another_mode_or_version_is_refused(fresh: Path) -> None:
    m = _write_manifest(fresh)
    (fresh / bundle.MANIFEST_NAME).write_text(json.dumps({**m, "kind": "pune"}))
    assert any("not 'sample'" in p for p in bundle.check_bundle(fresh, MODE).problems)
    (fresh / bundle.MANIFEST_NAME).write_text(json.dumps({**m, "manifest_version": 99}))
    assert any("unknown manifest version" in p for p in bundle.check_bundle(fresh, MODE).problems)


def test_a_missing_database_is_a_clear_problem(tmp_path: Path) -> None:
    rep = bundle.check_bundle(tmp_path, MODE)
    assert not rep.ok and "missing database" in rep.problems[0]


# ---------------------------------------------------------------------------- the CLI and the API
def test_bundle_check_command_exit_codes(fresh: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["bundle-check", "--root", str(fresh), "--mode", MODE]
    assert cli_main(argv) == 0  # no manifest: a warning, not a failure
    assert "warning" in capsys.readouterr().err
    assert cli_main([*argv, "--strict"]) == 1  # strict: warnings fail
    _write_manifest(fresh)
    assert cli_main([*argv, "--strict"]) == 0  # a consistent bundle passes strictly
    (fresh / "artifacts" / MODE / "forecast" / "evaluation.json").write_text("{}")
    assert cli_main(argv) == 1  # a tampered file is a failure
    assert "PROBLEM" in capsys.readouterr().err


def test_the_api_reports_the_bundle_it_is_serving(fresh: Path) -> None:
    settings = Settings.from_env(
        {"MOBILITYOPS_DATA_DIR": str(fresh / "data"), "MOBILITYOPS_MODE": MODE}
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/meta").json()["bundle"] is None  # no manifest, nothing claimed
    m = _write_manifest(fresh)
    with TestClient(create_app(settings)) as client:
        got = client.get("/api/v1/meta").json()["bundle"]
    assert got["data_run_id"] == m["data_run_id"] and got["model_id"] == m["model_id"]
    assert got["consistent"] is True and got["files_sha256"] == m["files_sha256"]
    assert got["schema_version"] == bundle.SCHEMA_VERSION
