"""Scenario storage for the DSSE workbench.

Grava no repo (`simulacao/cenarios_app`) em dev e em `%APPDATA%` quando
empacotado -- ver `app.backend.paths` para a razao.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..paths import display_path, scenario_dir

router = APIRouter()


class ScenarioPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: Literal["topology", "powerflow", "state_estimation", "bad_data", "workbench"]
    topology: dict[str, Any]
    settings: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    notes: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return slug or "scenario"


def _scenario_path(scenario_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", scenario_id):
        raise HTTPException(status_code=400, detail="Invalid scenario id.")
    return scenario_dir() / f"{scenario_id}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid scenario JSON: {path.name}") from exc


@router.get("/")
def list_scenarios() -> list[dict[str, Any]]:
    """List saved scenario metadata without loading heavy payloads in the UI."""
    directory = scenario_dir()
    directory.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(directory.glob("*.json")):
        data = _read_json(path)
        items.append(
            {
                "id": data.get("id", path.stem),
                "name": data.get("name", path.stem),
                "kind": data.get("kind", "topology"),
                "topologyName": data.get("topology", {}).get("name"),
                "createdAt": data.get("createdAt"),
                "updatedAt": data.get("updatedAt"),
            }
        )
    return items


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str) -> dict[str, Any]:
    path = _scenario_path(scenario_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")
    return _read_json(path)


@router.post("/")
def save_scenario(payload: ScenarioPayload) -> dict[str, Any]:
    """Save a new scenario snapshot as a JSON file on the writable data dir."""
    scenario_dir().mkdir(parents=True, exist_ok=True)
    base_id = _slugify(payload.name)
    scenario_id = base_id
    i = 2
    while _scenario_path(scenario_id).exists():
        scenario_id = f"{base_id}-{i}"
        i += 1

    now = _now_iso()
    data = {
        "id": scenario_id,
        "name": payload.name,
        "kind": payload.kind,
        "topology": payload.topology,
        "settings": payload.settings,
        "result": payload.result,
        "notes": payload.notes,
        "createdAt": now,
        "updatedAt": now,
    }
    _scenario_path(scenario_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"id": scenario_id, "path": display_path(_scenario_path(scenario_id))}


@router.put("/{scenario_id}")
def overwrite_scenario(scenario_id: str, payload: ScenarioPayload) -> dict[str, Any]:
    """Overwrite an existing scenario while preserving its creation time if present."""
    scenario_dir().mkdir(parents=True, exist_ok=True)
    path = _scenario_path(scenario_id)
    previous = _read_json(path) if path.exists() else {}
    now = _now_iso()
    data = {
        "id": scenario_id,
        "name": payload.name,
        "kind": payload.kind,
        "topology": payload.topology,
        "settings": payload.settings,
        "result": payload.result,
        "notes": payload.notes,
        "createdAt": previous.get("createdAt", now),
        "updatedAt": now,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": scenario_id, "path": display_path(path)}
