"""The AI copilot across regions: real isolation (never answer Pune using Mumbai's data or vice
versa), an honest side-by-side comparison that never merges two regions' numbers, and that an
invalid region is rejected before it ever reaches a tool. Builds real (if small) Pune and Mumbai
datasets with the same fast, no-network harness ``test_pune_build.py``/``test_pune_state_api.py``
already use, under one shared data directory - the real production layout."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mobilityops.analyst.planner import RulePlanner
from mobilityops.analyst.regions import RegionRegistry
from mobilityops.analyst.tools import call_tool
from mobilityops.api.app import create_app
from mobilityops.config import Settings
from mobilityops.forecasting.evaluate import train_final
from mobilityops.pune import build as pb
from tests.integration.test_pune_worker import WINDOW, _weather_frame


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):  # type: ignore[no-untyped-def]
    return tmp_path_factory.mktemp("regions") / "data"


@pytest.fixture(scope="module")
def pune_settings(data_dir):  # type: ignore[no-untyped-def]
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(data_dir), "MOBILITYOPS_MODE": "pune"})
    pb.build_pune(s, WINDOW, weather=_weather_frame())
    train_final(s)
    return s


@pytest.fixture(scope="module")
def mumbai_settings(data_dir):  # type: ignore[no-untyped-def]
    s = Settings.from_env({"MOBILITYOPS_DATA_DIR": str(data_dir), "MOBILITYOPS_MODE": "mumbai"})
    pb.build_pune(s, WINDOW, weather=_weather_frame())
    train_final(s)
    return s


@pytest.fixture()
def registry(pune_settings, mumbai_settings):  # type: ignore[no-untyped-def]
    return RegionRegistry(pune_settings, RulePlanner())


def test_a_mumbai_only_zone_does_not_resolve_in_pune(registry) -> None:  # type: ignore[no-untyped-def]
    pune = registry.analyst_for("pune")
    mumbai = registry.analyst_for("mumbai")
    args = {"zone": "Colaba", "start": str(WINDOW[0]), "end": str(WINDOW[1])}
    in_pune = call_tool(pune.services, "c1", "get_zone_metrics", args)
    assert in_pune.ok is False, "Colaba is a real Mumbai zone and must not exist in Pune's 91"
    in_mumbai = call_tool(mumbai.services, "c1", "get_zone_metrics", args)
    assert in_mumbai.ok is True
    assert in_mumbai.data["zone"] == "Colaba"


def test_compare_regions_keeps_every_number_scoped_to_its_side(registry) -> None:  # type: ignore[no-untyped-def]
    pune = registry.analyst_for("pune")
    r = call_tool(
        pune.services, "c1", "compare_regions", {"region_a": "pune", "region_b": "mumbai"}, registry=registry
    )
    assert r.ok, r.error
    assert r.data["a"]["city"] == "Pune" and r.data["b"]["city"] == "Mumbai"
    assert r.data["a"]["zones"] == 91, "Pune's real zone count"
    assert r.data["b"]["zones"] == 277, "Mumbai's real zone count"
    # Every fact id is explicitly prefixed a./b.: nothing is merged into one shared key.
    assert r.facts["c1.a.zones"].value == 91
    assert r.facts["c1.b.zones"].value == 277
    assert r.facts["c1.a.zones"].value != r.facts["c1.b.zones"].value


def test_compare_regions_refuses_to_compare_a_region_with_itself(registry) -> None:  # type: ignore[no-untyped-def]
    pune = registry.analyst_for("pune")
    r = call_tool(
        pune.services, "c1", "compare_regions", {"region_a": "pune", "region_b": "pune"}, registry=registry
    )
    assert r.ok is False


def test_compare_regions_is_honest_when_one_side_has_no_data(pune_settings, mumbai_settings) -> None:  # type: ignore[no-untyped-def]
    # A fresh registry pointed only at a data_dir that has Pune but never built real's NYC data:
    # the real-mode side must say so, not invent numbers or silently omit the side.
    registry = RegionRegistry(pune_settings, RulePlanner())
    pune = registry.analyst_for("pune")
    r = call_tool(
        pune.services, "c1", "compare_regions", {"region_a": "pune", "region_b": "real"}, registry=registry
    )
    assert r.ok
    assert r.data["b"]["available"] is False
    assert "c1.b.status" in r.facts and "not ready" in r.facts["c1.b.status"].value


def test_ask_endpoint_switches_region_live_without_restarting_the_app(pune_settings, mumbai_settings) -> None:  # type: ignore[no-untyped-def]
    # One running app, started in Pune's own mode - proves region switching happens per request,
    # not by picking which process/deployment you talk to.
    client = TestClient(create_app(pune_settings))
    q = "What were the busiest zones last week?"  # the exact example the web UI offers
    default = client.post("/api/v1/analyst/ask", json={"question": q}).json()
    mumbai = client.post("/api/v1/analyst/ask", json={"question": q, "region": "mumbai"}).json()
    assert default["region"] == "pune" and mumbai["region"] == "mumbai"
    assert default["status"] in ("answered", "partial")
    assert mumbai["status"] in ("answered", "partial")

    def zone_names(resp: dict) -> set[str]:  # type: ignore[type-arg]
        return {
            f["value"]
            for t in resp["tools_used"]
            for f in t["facts"]
            if "zone" in f["label"].lower() and isinstance(f["value"], str)
        }

    pune_zones, mumbai_zones = zone_names(default), zone_names(mumbai)
    assert pune_zones and mumbai_zones, "both answers should cite real zone names"
    assert pune_zones.isdisjoint(mumbai_zones), "the two regions' busiest zones must never overlap"


def test_ask_endpoint_rejects_an_unknown_region_before_any_tool_runs(pune_settings) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(pune_settings))
    r = client.post(
        "/api/v1/analyst/ask", json={"question": "Compare Pune and Mumbai", "region": "atlantis"}
    )
    assert r.status_code == 422


def test_analyst_regions_endpoint_lists_the_three_selectable_regions(pune_settings) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(pune_settings))
    r = client.get("/api/v1/analyst/regions")
    assert r.status_code == 200
    assert r.json() == {"real": "New York", "pune": "Pune", "mumbai": "Mumbai"}
