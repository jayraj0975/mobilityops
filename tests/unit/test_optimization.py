"""The repositioning optimiser against cases with known answers, including brute force."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from mobilityops.optimization.model import (
    SIMULATION_LABEL,
    Instance,
    RebalanceParams,
    SolveStatus,
    served_trips,
    solve_rebalancing,
)
from mobilityops.optimization.scenario import Window, apportion


def make(demand, supply, lon=None, lat=None) -> Instance:  # type: ignore[no-untyped-def]
    n = len(demand)
    lon = np.linspace(-74.0, -73.99, n) if lon is None else np.asarray(lon, dtype=float)
    lat = np.full(n, 40.7) if lat is None else np.asarray(lat, dtype=float)
    return Instance(
        np.arange(1, n + 1),
        np.asarray(demand, dtype=float),
        np.asarray(supply, dtype=float),
        lon,
        lat,
    )


P1 = RebalanceParams(trips_per_vehicle=1.0, max_move_share=1.0, max_km=20.0)


# ------------------------------------------------------------------------ known answers
def test_moves_vehicles_to_where_the_demand_is() -> None:
    inst = make(demand=[2, 8], supply=[10, 0])
    r = solve_rebalancing(inst, P1)
    assert r.status is SolveStatus.OPTIMAL
    assert r.served_before == 2 and r.served_after == 10
    assert r.vehicles_moved == 8
    assert r.moves == [{"from_zone": 1, "to_zone": 2, "vehicles": 8, "km": r.moves[0]["km"]}]
    assert list(r.final_supply) == [2, 8]  # type: ignore[arg-type]


def test_distance_limit_blocks_moves() -> None:
    inst = make(demand=[2, 8], supply=[10, 0], lon=[-74.0, -73.5])  # ~42 km apart
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, max_km=6, max_move_share=1))
    assert r.moves == [] and r.served_after == r.served_before == 2
    assert r.solver["candidate_moves"] == 0


def test_move_budget_limits_moves() -> None:
    inst = make(demand=[2, 8], supply=[10, 0])
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, max_move_share=0.3))
    assert r.vehicles_moved == 3 and r.served_after == 5  # 2 at home + 3 moved


def test_no_moves_when_supply_already_matches_demand() -> None:
    r = solve_rebalancing(make(demand=[5, 5], supply=[5, 5]), P1)
    assert r.moves == [] and r.served_after == r.served_before == 10


def test_move_cost_can_make_a_move_not_worth_it() -> None:
    inst = make(demand=[0, 1], supply=[1, 0], lon=[-74.0, -73.96])  # ~3.4 km apart
    cheap = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, cost_per_km=0.05,
                                                     max_move_share=1))  # fmt: skip
    dear = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, cost_per_km=0.5,
                                                    max_move_share=1))  # fmt: skip
    assert cheap.vehicles_moved == 1 and cheap.served_after == 1  # gain 1 > cost 0.17
    assert dear.vehicles_moved == 0 and dear.served_after == 0  # gain 1 < cost 1.7


def test_capacity_per_vehicle_scales_what_a_vehicle_can_serve() -> None:
    inst = make(demand=[0, 9], supply=[3, 0])
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=3.0, max_move_share=1))
    assert r.served_after == 9 and r.vehicles_moved == 3


def test_zones_without_a_centroid_neither_send_nor_receive() -> None:
    inst = make(demand=[0, 8, 8], supply=[8, 0, 0], lon=[-74.0, -73.995, np.nan])
    r = solve_rebalancing(inst, P1)
    assert r.final_supply[2] == 0  # type: ignore[index]
    assert all(m["to_zone"] != 3 and m["from_zone"] != 3 for m in r.moves)


# ------------------------------------------------------------- infeasible / edge cases
def test_unreachable_service_level_is_reported_infeasible_with_the_best_attainable() -> None:
    inst = make(demand=[2, 8], supply=[3, 3])  # capacity 6 < demand 10
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, max_move_share=1,
                                                min_service_share=0.95))  # fmt: skip
    assert r.status is SolveStatus.INFEASIBLE
    assert r.best_attainable_service_share == pytest.approx(0.6)
    assert "60.0%" in r.message and "95.0%" in r.message
    assert r.to_dict()["status"] == "infeasible"


def test_service_level_that_is_reachable_by_moving_is_satisfied() -> None:
    inst = make(demand=[2, 8], supply=[10, 0])
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, max_move_share=1,
                                                min_service_share=0.95))  # fmt: skip
    assert r.status is SolveStatus.OPTIMAL and r.service_share_after == 1.0


def test_service_level_blocked_by_the_move_budget_is_infeasible() -> None:
    inst = make(demand=[2, 8], supply=[10, 0])
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, max_move_share=0.1,
                                                min_service_share=0.9))  # fmt: skip
    assert r.status is SolveStatus.INFEASIBLE
    assert r.best_attainable_service_share == pytest.approx(0.3)  # 2 + 1 moved of 10


def test_no_pairs_and_service_requirement_is_infeasible_not_silent() -> None:
    inst = make(demand=[2, 8], supply=[10, 0], lon=[-74.0, -73.5])
    r = solve_rebalancing(inst, RebalanceParams(trips_per_vehicle=1, min_service_share=0.9))
    assert r.status is SolveStatus.INFEASIBLE and r.best_attainable_service_share == 0.2


def test_empty_fleet_and_zero_demand_are_handled() -> None:
    r = solve_rebalancing(make(demand=[3, 3], supply=[0, 0]), P1)
    assert r.status is SolveStatus.OPTIMAL and r.served_after == 0 and r.fleet == 0
    r0 = solve_rebalancing(make(demand=[0, 0], supply=[2, 2]), P1)
    assert r0.moves == [] and r0.service_share_after is None


def test_every_result_is_labelled_a_simulation_and_echoes_assumptions() -> None:
    r = solve_rebalancing(make(demand=[2, 8], supply=[10, 0]), P1)
    d = r.to_dict()
    assert d["label"] == SIMULATION_LABEL and "SIMULATED" in d["label"]
    assert d["assumptions"]["max_km"] == 20.0 and d["assumptions"]["trips_per_vehicle"] == 1.0


# ------------------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "kwargs",
    [
        {"trips_per_vehicle": 0},
        {"max_km": -1},
        {"cost_per_km": -0.1},
        {"max_move_share": 1.5},
        {"min_service_share": 0},
        {"min_service_share": 1.2},
    ],
)
def test_parameter_validation(kwargs) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        solve_rebalancing(make(demand=[1, 1], supply=[1, 1]), RebalanceParams(**kwargs))


def test_instance_validation() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        solve_rebalancing(make(demand=[-1, 1], supply=[1, 1]))
    with pytest.raises(ValueError, match="whole vehicles"):
        solve_rebalancing(make(demand=[1, 1], supply=[1.5, 1]))
    with pytest.raises(ValueError, match="one entry per zone"):
        solve_rebalancing(Instance(np.arange(3), np.ones(3), np.ones(2), np.zeros(3), np.zeros(3)))


# ------------------------------------------------------------------------ invariants
def _random_instance(rng: np.random.Generator, n: int) -> Instance:
    return make(
        demand=rng.integers(0, 15, n),
        supply=rng.integers(0, 6, n),
        lon=-74.0 + rng.random(n) * 0.05,
        lat=40.7 + rng.random(n) * 0.05,
    )


@pytest.mark.parametrize("seed", range(12))
def test_solution_respects_conservation_budget_distance_and_never_hurts(seed: int) -> None:
    rng = np.random.default_rng(seed)
    inst = _random_instance(rng, 12)
    params = RebalanceParams(trips_per_vehicle=2.0, max_km=3.0, max_move_share=0.25,
                             cost_per_km=0.01)  # fmt: skip
    r = solve_rebalancing(inst, params)
    assert r.status is SolveStatus.OPTIMAL
    final = np.asarray(r.final_supply)
    assert final.sum() == inst.supply.sum()  # vehicles are conserved
    assert (final >= 0).all() and np.allclose(final, np.round(final))
    assert r.vehicles_moved <= np.floor(0.25 * inst.fleet + 1e-9)
    assert all(m["km"] <= 3.0 + 1e-9 for m in r.moves)  # distance limit
    for m in r.moves:  # cannot send more than a zone started with
        assert m["vehicles"] <= inst.supply[m["from_zone"] - 1]
    assert r.served_after >= r.served_before - 1e-9  # never worse than doing nothing
    assert r.served_after == pytest.approx(served_trips(inst.demand, final, 2.0))


def _brute_force_best(demand: np.ndarray, fleet: int, c: float) -> float:
    n = len(demand)
    best = 0.0
    for comp in itertools.product(range(fleet + 1), repeat=n):
        if sum(comp) == fleet:
            best = max(best, float(np.minimum(demand, c * np.array(comp)).sum()))
    return best


@pytest.mark.parametrize("seed", range(10))
def test_matches_brute_force_optimum_when_every_move_is_allowed(seed: int) -> None:
    """Unlimited budget/distance and free moves: the optimum is a pure allocation problem."""
    rng = np.random.default_rng(100 + seed)
    n = 4
    inst = make(demand=rng.integers(0, 8, n), supply=rng.integers(0, 4, n))
    params = RebalanceParams(trips_per_vehicle=2.0, max_km=100.0, max_move_share=1.0,
                             cost_per_km=0.0)  # fmt: skip
    r = solve_rebalancing(inst, params)
    assert r.served_after == pytest.approx(_brute_force_best(inst.demand, inst.fleet, 2.0))


@pytest.mark.parametrize("seed", range(6))
def test_lp_relaxation_is_an_upper_bound_on_the_integer_solution(seed: int) -> None:
    rng = np.random.default_rng(300 + seed)
    inst = _random_instance(rng, 10)
    common = {"trips_per_vehicle": 1.7, "max_km": 4.0, "max_move_share": 0.4, "cost_per_km": 0.0}
    lp = solve_rebalancing(inst, RebalanceParams(integer=False, **common))
    ip = solve_rebalancing(inst, RebalanceParams(integer=True, **common))
    assert lp.served_after >= ip.served_after - 1e-6


# ---------------------------------------------------------------------- helpers
def test_apportion_is_exact_proportional_and_handles_bad_weights() -> None:
    out = apportion(np.array([1.0, 1.0, 1.0]), 10)
    assert out.sum() == 10 and sorted(out.tolist()) == [3, 3, 4]
    assert apportion(np.array([3.0, 1.0]), 8).tolist() == [6, 2]
    assert apportion(np.array([0.0, 0.0]), 5).tolist() == [0, 0]
    assert apportion(np.array([np.nan, 2.0]), 4).tolist() == [0, 4]
    assert apportion(np.array([1.0, 2.0]), 0).tolist() == [0, 0]


def test_window_validation() -> None:
    assert Window(7, 10).hours == 3 and Window(7, 10).label == "07:00-10:00"
    for bad in ((10, 10), (-1, 5), (5, 25)):
        with pytest.raises(ValueError):
            Window(*bad)


# ------------------------------------------------- regression: every solver status is handled
from mobilityops.optimization import model as opt_model  # noqa: E402
from mobilityops.optimization.model import classify_solver_status  # noqa: E402


@pytest.mark.parametrize(
    ("code", "has_solution", "expected"),
    [
        (0, True, SolveStatus.OPTIMAL),
        (1, True, SolveStatus.FEASIBLE_TIME_LIMIT),
        (1, False, SolveStatus.NO_SOLUTION),
        (2, False, SolveStatus.INFEASIBLE),
        (3, False, SolveStatus.UNBOUNDED),
        (4, True, SolveStatus.SOLVER_ERROR),
        (4, False, SolveStatus.SOLVER_ERROR),
        (7, True, SolveStatus.SOLVER_ERROR),  # an unrecognised code is an error, never a time limit
        (-1, True, SolveStatus.SOLVER_ERROR),
    ],
)
def test_every_solver_status_maps_to_its_own_outcome(
    code: int, has_solution: bool, expected: SolveStatus
) -> None:
    status, why = classify_solver_status(code, has_solution)
    assert status is expected and why


def test_only_a_real_limit_is_ever_reported_as_a_time_limit() -> None:
    limit = {
        c
        for c in range(-3, 10)
        if classify_solver_status(c, True)[0] is SolveStatus.FEASIBLE_TIME_LIMIT
    }
    assert limit == {1}


@pytest.mark.parametrize("code", [3, 4, 5, 99])
def test_a_plan_from_an_untrustworthy_solve_is_never_shown(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A solver can report numerical trouble yet return a vector; that plan must not be shown."""
    real = opt_model._solve

    def faulty(*args, **kwargs):  # type: ignore[no-untyped-def]
        res, cost = real(*args, **kwargs)
        assert res.x is not None  # the underlying solve is good; only its reported status is forced
        res.status = code
        return res, cost

    monkeypatch.setattr(opt_model, "_solve", faulty)
    r = solve_rebalancing(make(demand=[2, 8], supply=[10, 0]), P1)
    assert r.status in (SolveStatus.UNBOUNDED, SolveStatus.SOLVER_ERROR)
    assert r.moves == [] and r.vehicles_moved in (0, None)
    assert "not trusted" in r.message or "unbounded" in r.message or "unrecognised" in r.message


def test_a_time_limit_with_a_solution_still_returns_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = opt_model._solve

    def limited(*args, **kwargs):  # type: ignore[no-untyped-def]
        res, cost = real(*args, **kwargs)
        res.status = 1
        return res, cost

    monkeypatch.setattr(opt_model, "_solve", limited)
    r = solve_rebalancing(make(demand=[2, 8], supply=[10, 0]), P1)
    assert r.status is SolveStatus.FEASIBLE_TIME_LIMIT and r.moves and "not proven" in r.message
