"""Edition config API routes — list editions and get edition configuration."""


from fastapi import APIRouter, Depends, HTTPException, Path

from apps.api_server.dependencies import require_permission

from packages.agent_core.edition_manager import EditionManager

router = APIRouter()


def _get_edition_manager() -> EditionManager:
    return EditionManager()


@router.get("", dependencies=[Depends(require_permission("editions", "read"))])
def list_editions():
    """List all available editions with summary info."""
    mgr = _get_edition_manager()
    editions = mgr.list_editions()
    edition_details = [
        {
            "edition": e,
            "name": mgr.get_name(e),
            "description": mgr.get_description(e),
        }
        for e in editions
    ]
    return {"success": True, "data": edition_details}


@router.get("/{edition}", dependencies=[Depends(require_permission("editions", "read"))])
def get_edition(edition: str = Path(..., min_length=1, max_length=50)):
    """Get full configuration for a specific edition.

    Unknown editions return 404 from the handler (not 422 path-validation)
    so clients can distinguish "invalid name format" from "no such edition".
    """
    mgr = _get_edition_manager()
    config = mgr.get_config(edition)
    if not config:
        raise HTTPException(status_code=404, detail=f"Edition '{edition}' not found")

    return {
        "success": True,
        "data": {
            "edition": edition,
            "name": mgr.get_name(edition),
            "description": mgr.get_description(edition),
            "tools": {
                "enabled": mgr.get_enabled_tools(edition),
                "disabled": mgr.get_disabled_tools(edition),
            },
            "policy": {
                "max_risk_level": mgr.get_max_risk_level(edition),
                "auto_approve_low_risk": mgr.auto_approve_low_risk(edition),
            },
            "memory": {
                "types": mgr.get_memory_types(edition),
                "retention_days": mgr.get_retention_days(edition),
            },
            "is_personal": mgr.is_personal(edition),
            "is_enterprise": mgr.is_enterprise(edition),
        },
    }
