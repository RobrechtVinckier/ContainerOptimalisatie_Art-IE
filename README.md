# Haven Antwerpen Hackathon

Monorepo with:
- `frontend/`: 3D yard visualization (Vite, vanilla JS, Three.js)
- `backend/`: FastAPI service that generates yard states and runs the optimization algorithm
- `algorithm/`: optimization engine used by the backend
- `documents/`: presentation material for the project

## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend expects backend at `http://localhost:8000` by default.
Set `VITE_API_BASE_URL` if needed.

## Run Backend

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --reload --port 8000
```

If the virtual environment already exists, you only need:

```bash
source .venv/bin/activate
python -m uvicorn backend.app.main:app --reload --port 8000
```

## API Endpoints

- `GET /api/config`
- `POST /api/simulations/random`
- `POST /api/simulations/solve`
- `GET /api/algorithm/settings`
- `PATCH /api/algorithm/settings`
