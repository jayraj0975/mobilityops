"""Vehicle repositioning as a mixed-integer linear program (a *simulation*, not a prediction).

**Every output of this module is a SIMULATED SCENARIO under explicit assumptions.** No fleet
data exist in the TLC open data, so supply, vehicle capacity, repositioning cost and speed are
assumptions the caller states (and that are echoed in every result). The optimiser answers a narrow
question: *given expected demand per zone for a window and a starting distribution of vehicles, how
should a limited number of vehicles be repositioned between nearby zones to serve as many trips as
possible?* It does not say what a real operator would achieve.

Model
-----
Zones ``i``. ``s_i`` vehicles start in zone ``i``; ``d_j`` trips are expected in zone ``j`` during
the window; one vehicle can serve at most ``c`` trips in the window. Decision ``x_ij`` (integer)
vehicles move ``i -> j`` for pairs at most ``max_km`` apart. Then ``y_j = s_j - out_j + in_j``
vehicles are present in ``j`` and ``served_j = min(d_j, c * y_j)`` (modelled with ``u_j``).

    maximise    sum_j u_j  -  cost_per_km * sum_ij km_ij * x_ij
    subject to  u_j <= d_j,   u_j <= c * y_j,   sum_j x_ij <= s_i,
                sum_ij x_ij <= max_move_share * fleet,
                [optional] sum_j u_j >= min_service_share * sum_j d_j

Simplifications, all deliberate and stated: demand is served only in the zone where a vehicle
stands (no spill-over to neighbours); vehicles reach their destination before the window starts;
the cost of a move is linear in kilometres; zones without a known centroid cannot send or receive
vehicles; demand is treated as known (a forecast or the actual, chosen by the caller).

An infeasible request (for example a service level no repositioning can reach) is reported as such
with the best attainable value, never as a silent best-effort answer.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack

from mobilityops.geo import haversine_matrix_km

SIMULATION_LABEL = (
    "SIMULATED SCENARIO under explicit assumptions; not a forecast of real-world outcomes"
)


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_TIME_LIMIT = "feasible_time_limit"  # best solution found, optimality not proven
    INFEASIBLE = "infeasible"
    NO_SOLUTION = "no_solution"  # time limit hit before any solution
    UNBOUNDED = "unbounded"  # the model has no finite optimum: a formulation error, never a plan
    SOLVER_ERROR = "solver_error"  # numerical trouble or an unrecognised status: not to be trusted


# SciPy's ``milp`` exit statuses (scipy.optimize.milp): 0 optimal, 1 iteration or time limit,
# 2 infeasible, 3 unbounded, 4 other (numerical difficulties). Every one is handled explicitly: a
# status that is not recognised must never be presented as a benign time limit.
_MILP_STATUS = {0: "optimal", 1: "limit", 2: "infeasible", 3: "unbounded", 4: "other"}


def classify_solver_status(code: int, has_solution: bool) -> tuple[SolveStatus, str]:
    """Map a SciPy ``milp`` exit status to a :class:`SolveStatus` and an explanation."""
    kind = _MILP_STATUS.get(int(code))
    if kind == "optimal":
        return SolveStatus.OPTIMAL, "optimal under the stated assumptions"
    if kind == "limit":
        if has_solution:
            return (
                SolveStatus.FEASIBLE_TIME_LIMIT,
                "time or iteration limit reached: best solution found, optimality not proven",
            )
        return (
            SolveStatus.NO_SOLUTION,
            "the time or iteration limit was reached before any solution",
        )
    if kind == "infeasible":
        return SolveStatus.INFEASIBLE, "the request is infeasible under these assumptions"
    if kind == "unbounded":
        return (
            SolveStatus.UNBOUNDED,
            "the solver reports the model as unbounded (a formulation error); no plan is shown",
        )
    if kind == "other":
        return (
            SolveStatus.SOLVER_ERROR,
            "the solver reported numerical difficulties; any plan it returned is not trusted "
            "and is not shown",
        )
    return (
        SolveStatus.SOLVER_ERROR,
        f"the solver returned an unrecognised status ({code}); no plan is shown",
    )


@dataclass(frozen=True)
class RebalanceParams:
    trips_per_vehicle: float = 4.5  # ASSUMPTION: trips one vehicle serves in the window
    max_km: float = 6.0  # ASSUMPTION: farthest a vehicle may reposition (centroid to centroid)
    cost_per_km: float = 0.02  # ASSUMPTION: trips of value lost per vehicle-km driven empty
    max_move_share: float = 0.30  # ASSUMPTION: share of the fleet that may be repositioned
    min_service_share: float | None = None  # optional requirement: served / demand >= this
    integer: bool = True  # whole vehicles; False gives the LP relaxation (an upper bound)
    time_limit_s: float = 20.0
    mip_rel_gap: float = 1e-4

    def validate(self) -> None:
        if self.trips_per_vehicle <= 0:
            raise ValueError("trips_per_vehicle must be positive")
        if self.max_km <= 0:
            raise ValueError("max_km must be positive")
        if self.cost_per_km < 0:
            raise ValueError("cost_per_km must not be negative")
        if not 0 <= self.max_move_share <= 1:
            raise ValueError("max_move_share must be between 0 and 1")
        if self.min_service_share is not None and not 0 < self.min_service_share <= 1:
            raise ValueError("min_service_share must be in (0, 1]")


@dataclass(frozen=True)
class Instance:
    zone_ids: np.ndarray  # (Z,) location ids
    demand: np.ndarray  # (Z,) expected trips in the window
    supply: np.ndarray  # (Z,) vehicles at the start (non-negative integers)
    lon: np.ndarray  # (Z,) centroid; NaN => the zone cannot send or receive vehicles
    lat: np.ndarray

    def validate(self) -> None:
        n = len(self.zone_ids)
        for name in ("demand", "supply", "lon", "lat"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} must have one entry per zone")
        if (self.demand < 0).any() or np.isnan(self.demand).any():
            raise ValueError("demand must be non-negative and complete")
        if (self.supply < 0).any() or not np.allclose(self.supply, np.round(self.supply)):
            raise ValueError("supply must be non-negative whole vehicles")

    @property
    def fleet(self) -> int:
        return round(float(self.supply.sum()))


@dataclass
class ScenarioResult:
    status: SolveStatus
    message: str
    label: str = SIMULATION_LABEL
    fleet: int = 0
    demand_total: float = 0.0
    served_before: float = 0.0
    served_after: float = 0.0
    km_total: float = 0.0
    vehicles_moved: int = 0
    moves: list[dict[str, Any]] = field(default_factory=list)
    final_supply: np.ndarray | None = None
    best_attainable_service_share: float | None = None  # filled when a request is infeasible
    solver: dict[str, Any] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)

    @property
    def service_share_before(self) -> float | None:
        return self.served_before / self.demand_total if self.demand_total else None

    @property
    def service_share_after(self) -> float | None:
        return self.served_after / self.demand_total if self.demand_total else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["final_supply"] = None if self.final_supply is None else self.final_supply.tolist()
        d["service_share_before"] = self.service_share_before
        d["service_share_after"] = self.service_share_after
        return d


def served_trips(demand: np.ndarray, vehicles: np.ndarray, trips_per_vehicle: float) -> float:
    """Trips served if each zone serves ``min(demand, capacity)``."""
    return float(np.minimum(demand, trips_per_vehicle * vehicles).sum())


def candidate_pairs(inst: Instance, max_km: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Directed pairs (from, to, km) with a centroid on both ends, within ``max_km``."""
    dist = haversine_matrix_km(inst.lon, inst.lat)
    ok = np.isfinite(dist) & (dist <= max_km) & (dist > 0)
    ok &= (inst.supply > 0)[:, None]  # only zones that have vehicles can send any
    src, dst = np.nonzero(ok)
    return src, dst, dist[src, dst]


def _solve(
    inst: Instance, params: RebalanceParams, src: np.ndarray, dst: np.ndarray, km: np.ndarray,
    min_service: float | None,
) -> tuple[Any, np.ndarray]:  # fmt: skip
    z, p = len(inst.zone_ids), len(src)
    c, s, d = params.trips_per_vehicle, inst.supply, inst.demand
    n_var = p + z  # x (moves) then u (served trips per zone)
    cost = np.concatenate([params.cost_per_km * km, -np.ones(z)])  # minimise cost - served

    rows: list[Any] = []
    upper: list[np.ndarray] = []
    # (1) cannot move out more than are present
    rows.append(coo_matrix((np.ones(p), (src, np.arange(p))), shape=(z, n_var)))
    upper.append(s.astype(float))
    # (2) u_j + c*out_j - c*in_j <= c*s_j  (served <= capacity of vehicles present)
    a2 = coo_matrix(
        (
            np.concatenate([c * np.ones(p), -c * np.ones(p), np.ones(z)]),
            (
                np.concatenate([src, dst, np.arange(z)]),
                np.concatenate([np.arange(p), np.arange(p), p + np.arange(z)]),
            ),
        ),
        shape=(z, n_var),
    )
    rows.append(a2)
    upper.append(c * s.astype(float))
    # (3) repositioning budget
    budget = np.floor(params.max_move_share * inst.fleet + 1e-9)
    rows.append(coo_matrix((np.ones(p), (np.zeros(p, dtype=int), np.arange(p))), shape=(1, n_var)))
    upper.append(np.array([budget]))
    constraints = [LinearConstraint(vstack(rows).tocsr(), -np.inf, np.concatenate(upper))]
    # (4) optional minimum service level: sum(u) >= share * sum(d)
    if min_service is not None:
        a4 = coo_matrix((np.ones(z), (np.zeros(z, dtype=int), p + np.arange(z))), shape=(1, n_var))
        constraints.append(LinearConstraint(a4.tocsr(), min_service * d.sum(), np.inf))

    lb = np.zeros(n_var)
    ub = np.concatenate([s[src].astype(float), d.astype(float)])
    integrality = np.concatenate([np.ones(p) if params.integer else np.zeros(p), np.zeros(z)])
    res = milp(
        cost,
        constraints=constraints,
        bounds=Bounds(lb, ub),
        integrality=integrality,
        options={"time_limit": params.time_limit_s, "mip_rel_gap": params.mip_rel_gap},
    )
    return res, cost


def solve_rebalancing(inst: Instance, params: RebalanceParams | None = None) -> ScenarioResult:
    """Solve one repositioning scenario. Never raises for an infeasible request; it reports it."""
    params = params or RebalanceParams()
    params.validate()
    inst.validate()
    t0 = time.perf_counter()
    base = served_trips(inst.demand, inst.supply, params.trips_per_vehicle)
    result = ScenarioResult(
        status=SolveStatus.OPTIMAL,
        message="",
        fleet=inst.fleet,
        demand_total=float(inst.demand.sum()),
        served_before=base,
        served_after=base,
        final_supply=inst.supply.astype(int).copy(),
        assumptions={**asdict(params), "movement": "zone centroids, great-circle km"},
    )
    src, dst, km = candidate_pairs(inst, params.max_km)
    result.solver = {
        "name": "HiGHS via scipy.optimize.milp",
        "integer": params.integer,
        "candidate_moves": len(src),
    }
    if len(src) == 0 or inst.fleet == 0:
        result.message = "no feasible repositioning moves exist under these assumptions"
        result.solver["seconds"] = time.perf_counter() - t0
        return _check_service(result, params)

    res, _ = _solve(inst, params, src, dst, km, params.min_service_share)
    result.solver["seconds"] = time.perf_counter() - t0
    result.solver["highs_status"] = int(res.status)
    if res.status == 2:  # infeasible: report what IS attainable
        result.status = SolveStatus.INFEASIBLE
        relaxed, _ = _solve(inst, params, src, dst, km, None)
        best = None
        if relaxed.x is not None:
            best = float(relaxed.x[len(src) :].sum()) / max(result.demand_total, 1e-12)
        result.best_attainable_service_share = best
        need = params.min_service_share
        result.message = (
            f"infeasible: a service level of {need:.1%} cannot be reached under these "
            f"assumptions; the best attainable is "
            f"{'unknown' if best is None else format(best, '.1%')} "
            f"(limits: {params.max_move_share:.0%} of fleet repositioned, moves up to "
            f"{params.max_km:g} km, {inst.fleet} vehicles)"
        )
        return result
    outcome, explanation = classify_solver_status(res.status, res.x is not None)
    if outcome in (SolveStatus.UNBOUNDED, SolveStatus.SOLVER_ERROR):
        result.status = outcome  # never present a plan from an untrustworthy solve
        result.message = f"{explanation} ({res.message})"
        return result
    if res.x is None:
        result.status = SolveStatus.NO_SOLUTION
        result.message = f"the solver returned no solution: {explanation} ({res.message})"
        return result

    x = np.rint(res.x[: len(src)]) if params.integer else res.x[: len(src)]
    if params.integer and np.abs(res.x[: len(src)] - x).max() > 1e-4:
        result.status = SolveStatus.NO_SOLUTION
        result.message = "solver returned a non-integral vehicle count"
        return result
    final = inst.supply.astype(float).copy()
    np.subtract.at(final, src, x)
    np.add.at(final, dst, x)
    used = x > 1e-9
    result.moves = sorted(
        (
            {
                "from_zone": int(inst.zone_ids[a]),
                "to_zone": int(inst.zone_ids[b]),
                "vehicles": float(q) if not params.integer else int(q),
                "km": round(float(k), 2),
            }
            for a, b, q, k in zip(src[used], dst[used], x[used], km[used], strict=True)
        ),
        key=lambda m: -m["vehicles"],
    )
    result.final_supply = final.astype(int) if params.integer else final
    result.served_after = served_trips(inst.demand, final, params.trips_per_vehicle)
    result.vehicles_moved = round(float(x.sum()))
    result.km_total = float((x * km).sum())
    result.status = outcome  # OPTIMAL or FEASIBLE_TIME_LIMIT: the only two that carry a plan here
    result.solver["mip_gap"] = getattr(res, "mip_gap", None)
    result.message = explanation
    return _check_service(result, params)


def _check_service(result: ScenarioResult, params: RebalanceParams) -> ScenarioResult:
    """Apply the optional service requirement to the trivial (no-move) outcome too."""
    need = params.min_service_share
    unmet_without_moves = (
        need is not None
        and (result.service_share_after or 0.0) + 1e-9 < need
        and result.status is SolveStatus.OPTIMAL
        and not result.moves
    )
    if unmet_without_moves and need is not None:
        result.status = SolveStatus.INFEASIBLE
        result.best_attainable_service_share = result.service_share_after
        result.message = (
            f"infeasible: a service level of {need:.1%} cannot be reached; with no feasible "
            f"repositioning the attainable level is {result.service_share_after or 0:.1%}"
        )
    return result
