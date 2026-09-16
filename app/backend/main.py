"""FastAPI entry-point para o DSSE Simulation Workbench."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .paths import frontend_dist
from .routes import agents, baddata, estimation, pipeline, powerflow, scenarios, topology

app = FastAPI(
    title="DSSE Simulation API",
    description=(
        "Backend para o DSSE Simulation Workbench — power flow, state estimation, "
        "bad data, cadeia operacional SCADA e multi-agent framework."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(topology.router, prefix="/api/topologies", tags=["topology"])
app.include_router(powerflow.router, prefix="/api/powerflow", tags=["powerflow"])
app.include_router(estimation.router, prefix="/api/estimation", tags=["estimation"])
app.include_router(baddata.router, prefix="/api/baddata", tags=["baddata"])
app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


# Serve a SPA depois de todas as rotas /api, para que o mount em "/" nunca
# roube uma chamada de API. So tem efeito quando existe um build do Vite --
# ver `paths.frontend_dist`.
_dist = frontend_dist()
if _dist is not None:
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
