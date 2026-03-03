# Architecture Overview

## Modules

- `backend/app/main.py`
  - FastAPI adapter layer.
  - Converts HTTP requests to service calls and returns response models.
- `backend/app/database.py`
  - Backward-compatible facade.
  - Preserves existing public API/import paths.
  - Delegates to `backend/app/services/*`.
- `backend/app/core/constants.py`
  - Domain constants (yard dimensions, timing constants, company metadata).
- `backend/app/services/stack_service.py`
  - Yard stack primitives: cloning, normalization, summary, random configuration.
- `backend/app/services/timing_service.py`
  - Crane travel/energy timing formulas as pure functions.
- `backend/app/services/optimizer_service.py`
  - Conversion between backend stack payloads and algorithm `State`.
  - Optimizer config mapping and move conversion.
- `backend/app/services/night_stage_service.py`
  - Night staging heuristic before day cycle.
- `backend/app/services/day_cycle_service.py`
  - Day truck schedule builder and lane timing heuristics.
- `backend/app/services/solve_service.py`
  - Orchestrates greedy + tabu + day planning into final solve payload.

- `algorithm/state.py`
  - Core state model and delta cluster-cost logic.
- `algorithm/optimizer.py`
  - Compatibility shim that re-exports optimizer interfaces.
- `algorithm/core/optimizer_models.py`
  - Candidate/config/metrics data classes and type literals.
- `algorithm/core/candidate_generation.py`
  - Candidate enumeration and scoring.
- `algorithm/core/search.py`
  - Greedy planning and tabu search routines.
- `algorithm/main.py`
  - CLI adapter for algorithm experiments.

## Key Flows

## Random Simulation
1. `backend/app/main.py` receives `POST /api/simulations/random`.
2. Calls `database.random_configuration`.
3. Delegates to `stack_service.random_configuration`.
4. Returns seeded stacks + summary payload.

## Solve Simulation
1. `backend/app/main.py` receives `POST /api/simulations/solve`.
2. Calls `database.solve_stacks`.
3. `database` merges patch settings (compat behavior) and delegates to `solve_service.solve_stacks`.
4. `solve_service`:
   - builds algorithm state via `optimizer_service.state_from_stacks`,
   - runs `greedy_plan` and `tabu_improve`,
   - converts algorithm moves to frontend moves,
   - runs night staging (`night_stage_service`),
   - builds day cycle (`day_cycle_service`),
   - returns final contract payload.

## Extension Points

- Add new optimizer knobs in:
  - `backend/app/schemas.py` (`AlgorithmSettings`, `AlgorithmSettingsPatch`)
  - `backend/app/services/optimizer_service.py` (`optimizer_config`)
- Modify day scheduling policy in:
  - `backend/app/services/day_cycle_service.py`
- Adjust crane movement physics in:
  - `backend/app/services/timing_service.py`
- Keep external compatibility by preserving wrappers in:
  - `backend/app/database.py`
  - `algorithm/optimizer.py`

## Testing Strategy

- Unit and contract tests: `tests/`
- Snapshot baselines: `tests/snapshots/baseline_signatures.json`
- Smoke flow: `scripts/smoke_test.py`

