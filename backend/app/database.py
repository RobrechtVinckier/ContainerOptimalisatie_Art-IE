from .schemas import Container, Kraan, Wagen, Position, Dimensions
from datetime import datetime, timedelta
import random

# Configuration
COLUMNS = 10
ROWS = 5
MAX_HEIGHT = 4

# Mock storage
MOCK_CONTAINERS = []
MOCK_KRANEN = []
MOCK_WAGENS = []
MOCK_SHIPS = []
MOCK_HISTORY = []

def seed_data():
    global MOCK_CONTAINERS, MOCK_KRANEN, MOCK_WAGENS, MOCK_SHIPS, MOCK_HISTORY
    MOCK_CONTAINERS = []
    MOCK_KRANEN = []
    MOCK_WAGENS = []
    MOCK_SHIPS = []
    MOCK_HISTORY = []

    # 1. Seed Containers (Realistic Simulation State)
    # We'll fill about 70% of the grid positions with varying stack heights
    container_id = 1
    
    cities = ["Shanghai", "Singapore", "Rotterdam", "Antwerp", "Hamburg", "Ningbo", "Shenzhen", "Busan", "Dubai", "Los Angeles"]
    ships = ["MSC Oscar", "CMA CGM Marco Polo", "Maersk Mc-Kinney Moller", "Ever Golden", "HMM Algeciras"]
    urgencies = ["Low", "Normal", "High", "Critical"]
    
    for x in range(COLUMNS):
        for y in range(ROWS):
            # 70% chance to have a stack at this (x, y) coordinate
            if random.random() < 0.7:
                height = random.randint(1, MAX_HEIGHT)
                for z in range(height):
                    origin = random.choice(cities)
                    ship = random.choice(ships)
                    
                    MOCK_CONTAINERS.append({
                        "id": container_id,
                        "unit_nr": f"U-CONT-{1000 + container_id}",
                        "position": {"x": float(x), "y": float(y), "z": float(z)},
                        "arrival_time": datetime.now() - timedelta(days=random.randint(1, 5)),
                        "departure_time": datetime.now() + timedelta(days=random.randint(1, 10)),
                        "ship": ship,
                        "origin": origin,
                        "urgency": random.choice(urgencies),
                        "weight": round(random.uniform(5000, 30000), 2),  # Weight in kg
                        "status": "In Stack"
                    })
                    container_id += 1

    # 2. Seed Wagens (Vehicles) - Positioned along the row length (Columns)
    MOCK_WAGENS = [
        {
            "id": 1,
            "name": "Wagen-Alpha",
            "position_x": 2.5,  # Stationary between column 2 and 3
            "status": "Loading",
            "current_container_id": None
        },
        {
            "id": 2,
            "name": "Wagen-Beta",
            "position_x": 8.0,
            "status": "Moving",
            "current_container_id": None
        },
        {
            "id": 3,
            "name": "Wagen-Gamma",
            "position_x": 0.0,
            "status": "Idle",
            "current_container_id": None
        }
    ]

    # 3. Seed Cranes (Kraan)
    MOCK_KRANEN = [
        {
            "id": 1,
            "name": "Main-Gantry-01",
            "location": {"x": 2.5, "y": 2.0, "z": 8.0},
            "status": "Working",
            "current_container_id": None, # Will be set below
            "current_wagen_id": 1,
            "specifications": {"max_speed": "2m/s", "hoist_speed": "1m/s", "capacity": "45T"},
            "terminal": "Terminal-West",
            "dimensions": {"length": 12.2, "width": 2.4, "depth": 2.6}
        }
    ]

    # 4. Create an 'Active' simulation scenario:
    # Let's say Crane 1 is currently moving Container ID 1 to Wagen 1
    if MOCK_CONTAINERS:
        active_container = MOCK_CONTAINERS[0]
        active_container["status"] = "On Crane"
        MOCK_KRANEN[0]["current_container_id"] = active_container["id"]
        
        # And Wagen 2 is already carrying a container (let's add one specifically for it)
        wagen_container = {
            "id": container_id,
            "unit_nr": f"U-WAG-{2000}",
            "position": {"x": 8.0, "y": -1.0, "z": 0.0}, # -1 row indicates it's on the track
            "arrival_time": datetime.now(),
            "departure_time": datetime.now() + timedelta(hours=2),
            "ship": "Ever Given",
            "origin": "Terminal-West",
            "urgency": "High",
            "weight": 18000.0,
            "status": "On Wagen"
        }
        MOCK_CONTAINERS.append(wagen_container)
        MOCK_WAGENS[1]["current_container_id"] = wagen_container["id"]

    # 5. Seed Ships (Vessel Schedule)
    for ship_name in ships:
        MOCK_SHIPS.append({
            "name": ship_name,
            "departure_time": datetime.now() + timedelta(days=random.randint(1, 10), hours=random.randint(0, 23))
        })
    # Sort by departure time for the schedule
    MOCK_SHIPS.sort(key=lambda x: x["departure_time"])

# Initial seed
seed_data()

# --- Helper Functions ---

def get_all_containers():
    return MOCK_CONTAINERS

def get_all_kranen():
    return MOCK_KRANEN

def get_all_wagens():
    return MOCK_WAGENS

def get_all_ships():
    return MOCK_SHIPS

def get_history():
    return MOCK_HISTORY

def get_container_by_id(container_id: int):
    return next((c for c in MOCK_CONTAINERS if c["id"] == container_id), None)

def get_kraan_by_id(kraan_id: int):
    return next((k for k in MOCK_KRANEN if k["id"] == kraan_id), None)

def get_wagen_by_id(wagen_id: int):
    return next((w for w in MOCK_WAGENS if w["id"] == wagen_id), None)

def move_container(container_id: int, new_pos: dict, kraan_id: int):
    container = get_container_by_id(container_id)
    kraan = get_kraan_by_id(kraan_id)
    
    if not container or not kraan:
        return None
        
    old_pos = container["position"].copy()
    
    # Perform move
    container["position"] = new_pos
    kraan["location"] = new_pos  # Crane moves with the container
    
    # Log history
    history_entry = {
        "id": len(MOCK_HISTORY) + 1,
        "timestamp": datetime.now(),
        "container_id": container_id,
        "unit_nr": container["unit_nr"],
        "from_pos": old_pos,
        "to_pos": new_pos,
        "kraan_id": kraan_id
    }
    MOCK_HISTORY.append(history_entry)
    
    return history_entry
