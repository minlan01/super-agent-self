"""Plugin Management API — list, load, activate, deactivate plugins."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import PluginListResponse, ResponseBase

logger = logging.getLogger(__name__)

router = APIRouter()


class PluginActivateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.get("/list", response_model=PluginListResponse, dependencies=[Depends(require_permission("system", "read"))])
async def list_plugins() -> dict[str, Any]:
    """List all discovered plugins with their status."""
    from packages.plugins.loader import get_plugin_loader
    loader = get_plugin_loader()
    return {"success": True, "data": loader.list_plugins()}


@router.post("/discover", response_model=ResponseBase, dependencies=[Depends(require_permission("system", "admin"))])
async def discover_plugins() -> dict[str, Any]:
    """Scan plugin directory and load newly discovered plugins."""
    from packages.plugins.loader import get_plugin_loader
    loader = get_plugin_loader()
    results = loader.load_all()
    loaded = sum(1 for v in results.values() if v)
    return {"success": True, "message": f"Discovered {len(results)} plugins, {loaded} loaded"}


@router.post("/activate", response_model=ResponseBase, dependencies=[Depends(require_permission("system", "admin"))])
async def activate_plugin(body: PluginActivateRequest) -> dict[str, Any]:
    """Activate a loaded plugin."""
    from packages.plugins.loader import get_plugin_loader
    loader = get_plugin_loader()
    if loader.get_plugin(body.name) is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{body.name}' not found")
    success = await loader.activate(body.name)
    if not success:
        raise HTTPException(status_code=500, detail="Activation failed")
    return {"success": True, "message": f"Plugin '{body.name}' activated"}


@router.post("/deactivate", response_model=ResponseBase, dependencies=[Depends(require_permission("system", "admin"))])
async def deactivate_plugin(body: PluginActivateRequest) -> dict[str, Any]:
    """Deactivate an active plugin."""
    from packages.plugins.loader import get_plugin_loader
    loader = get_plugin_loader()
    success = await loader.deactivate(body.name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Plugin '{body.name}' not found")
    return {"success": True, "message": f"Plugin '{body.name}' deactivated"}


@router.post("/reload", response_model=ResponseBase, dependencies=[Depends(require_permission("system", "admin"))])
async def reload_plugin(body: PluginActivateRequest) -> dict[str, Any]:
    """Hot-reload a plugin."""
    from packages.plugins.loader import get_plugin_loader
    loader = get_plugin_loader()
    success = loader.reload(body.name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to reload plugin '{body.name}'")
    return {"success": True, "message": f"Plugin '{body.name}' reloaded"}
