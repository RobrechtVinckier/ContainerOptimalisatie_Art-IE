from fastapi import FastAPI, HTTPException
from typing import List
from . import schemas, database

app = FastAPI(
    title="Container Optimalisatie API",
    description="Full Terminal Simulation API (10x5x4 Grid) with Containers, Cranes, and Vehicles.",
    version="1.2.0"
)

@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Welcome to the Container Optimalisatie API",
        "layout": {
            "columns": 10,
            "rows": 5,
            "max_stack_height": 4,
            "logic": "Vehicles transport containers along the length (10 columns)."
        }
    }

# --- Container Endpoints ---

@app.get("/containers", response_model=List[schemas.Container], tags=["Containers"])
async def read_containers():
    """Get all containers in the 10x5x4 grid."""
    return database.get_all_containers()

@app.get("/containers/{container_id}", response_model=schemas.Container, tags=["Containers"])
async def read_container(container_id: int):
    container = database.get_container_by_id(container_id)
    if container is None:
        raise HTTPException(status_code=404, detail="Container not found")
    return container

# --- Kraan (Crane) Endpoints ---

@app.get("/kranen", response_model=List[schemas.Kraan], tags=["Kranen"])
async def read_kranen():
    """Get all cranes in the terminal."""
    return database.get_all_kranen()

@app.get("/kranen/{kraan_id}", response_model=schemas.Kraan, tags=["Kranen"])
async def read_kraan(kraan_id: int):
    kraan = database.get_kraan_by_id(kraan_id)
    if kraan is None:
        raise HTTPException(status_code=404, detail="Kraan not found")
    return kraan

# --- Wagen (Vehicle) Endpoints ---

@app.get("/wagens", response_model=List[schemas.Wagen], tags=["Wagens"])
async def read_wagens():
    """Get all transport vehicles (AGVs) moving along the columns."""
    return database.get_all_wagens()

@app.get("/wagens/{wagen_id}", response_model=schemas.Wagen, tags=["Wagens"])
async def read_wagen(wagen_id: int):
    wagen = database.get_wagen_by_id(wagen_id)
    if wagen is None:
        raise HTTPException(status_code=404, detail="Wagen not found")
    return wagen

@app.post("/seed", tags=["Simulation"])
async def reseed_simulation():
    """Reset the simulation with fresh random data in the 10x5x4 grid."""
    database.seed_data()
    return {"message": "Simulation data reset successfully"}

# --- Algorithm Integration Endpoints ---

@app.get("/ships", response_model=List[schemas.Ship], tags=["Algorithm"])
async def read_ships():
    """Get the vessel schedule (Ship names and departure times)."""
    return database.get_all_ships()

@app.post("/move", response_model=schemas.MoveHistory, tags=["Algorithm"])
async def move_container(command: schemas.MoveCommand):
    """Move a container to a new position. Returns the history entry of the move."""
    history_entry = database.move_container(
        command.container_id, 
        command.new_position.dict(), 
        command.kraan_id
    )
    if not history_entry:
        raise HTTPException(status_code=400, detail="Move failed. Check container and crane IDs.")
    return history_entry

@app.get("/history", response_model=List[schemas.MoveHistory], tags=["Algorithm"])
async def read_history():
    """Get the full history of moves performed during the simulation."""
    return database.get_history()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
