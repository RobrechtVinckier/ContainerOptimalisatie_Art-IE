from pydantic import BaseModel
from typing import Optional, Dict, List
from datetime import datetime

class Position(BaseModel):
    x: float  # Column index (0-9)
    y: float  # Row index (0-4)
    z: float  # Stack height index (0-3)

class Dimensions(BaseModel):
    length: float
    width: float
    depth: float

class TerminalLayout(BaseModel):
    columns: int = 10
    rows: int = 5
    stack_height: int = 4

class ContainerBase(BaseModel):
    unit_nr: str
    position: Position
    arrival_time: datetime
    departure_time: datetime
    ship: str
    origin: str
    urgency: Optional[str] = "Normal"
    weight: Optional[float] = None
    status: str = "In Stack"  # "In Stack", "On Crane", "On Wagen", "Departed"

class ContainerCreate(ContainerBase):
    pass

class Container(ContainerBase):
    id: int

    class Config:
        from_attributes = True

class WagenBase(BaseModel):
    name: str
    position_x: float  # Position along the 10 columns
    status: str  # "Idle", "Loading", "Moving", "Full"
    current_container_id: Optional[int] = None

class WagenCreate(WagenBase):
    pass

class Wagen(WagenBase):
    id: int

    class Config:
        from_attributes = True

class KraanBase(BaseModel):
    name: str
    location: Position
    status: str  # "Idle", "Working", "Maintenance"
    current_container_id: Optional[int] = None
    current_wagen_id: Optional[int] = None
    specifications: Dict[str, str]
    terminal: str
    dimensions: Dimensions

class KraanCreate(KraanBase):
    pass

class Kraan(KraanBase):
    id: int

    class Config:
        from_attributes = True
