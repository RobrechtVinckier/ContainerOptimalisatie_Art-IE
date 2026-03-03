from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import database, schemas

app = FastAPI(
    title="Container Yard Optimizer API",
    description="Backend service for yard randomization, optimization, and algorithm settings.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict:
    return {
        "message": "Container Yard Optimizer backend online",
        "frontend_dev": "npm run dev (from frontend/)",
        "backend_dev": "uvicorn backend.app.main:app --reload --port 8000",
        "endpoints": {
            "yard_config": "/api/config",
            "random": "/api/simulations/random",
            "solve": "/api/simulations/solve",
            "algorithm_settings": "/api/algorithm/settings",
        },
    }


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config", response_model=schemas.YardConfigResponse)
async def get_config() -> dict:
    return database.yard_config_payload()


@app.get("/api/algorithm/settings", response_model=schemas.AlgorithmSettings)
async def get_algorithm_settings() -> schemas.AlgorithmSettings:
    return database.get_algorithm_settings()


@app.patch("/api/algorithm/settings", response_model=schemas.AlgorithmSettings)
async def patch_algorithm_settings(payload: schemas.AlgorithmSettingsPatch) -> schemas.AlgorithmSettings:
    try:
        return database.update_algorithm_settings(payload)
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/simulations/random", response_model=schemas.RandomSimulationResponse)
async def create_random_simulation(payload: schemas.RandomSimulationRequest) -> dict:
    try:
        return database.random_configuration(
            seed=payload.seed,
            container_count=payload.containerCount,
            groups=payload.groups,
            containers_per_group=payload.containersPerGroup,
            min_containers_per_group=payload.minContainersPerGroup,
            max_containers_per_group=payload.maxContainersPerGroup,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/simulations/solve", response_model=schemas.SolveSimulationResponse)
async def solve_simulation(payload: schemas.SolveSimulationRequest) -> dict:
    try:
        return database.solve_stacks(payload.stacks, settings_patch=payload.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
