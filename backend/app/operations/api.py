import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import check_origin
from app.operations.diagnostics import collect_diagnostics


def control_authorization(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.sim_mode:
        raise HTTPException(404, "Simulation controls are disabled")
    supplied = request.headers.get("X-Sim-Control-Token", "")
    if not secrets.compare_digest(
        supplied.encode(), settings.sim_control_token.get_secret_value().encode()
    ):
        raise HTTPException(401, "Simulation control authorization required")


router = APIRouter(
    prefix="/sim", dependencies=[Depends(control_authorization), Depends(check_origin)]
)


@router.get("/capabilities")
def capabilities(request: Request):
    return {
        "project": "pinterest-lite",
        "contract_version": "1",
        "environment_id": request.app.state.settings.sim_environment_id,
        "ready_for_traffic": False,
        "surfaces": [],
        "event_types": [],
        "supports_diagnostics": True,
        "supports_users": False,
        "supports_catalog": False,
        "supports_runs": False,
        "supports_reset": False,
        "supports_snapshot": False,
        "supports_logical_time": False,
        "supports_model_control": False,
        "supports_train": False,
        "pending": [
            "phase2_feed_and_events",
            "run_registration_and_attribution",
            "user_and_catalog_adapter",
            "quiescent_baseline_reset",
        ],
    }


@router.get("/diagnostics")
def diagnostics(request: Request):
    state = request.app.state
    return collect_diagnostics(state.engine, state.queue, state.request_metrics)


@router.api_route("/{operation:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def unsupported_operation():
    raise HTTPException(501, "Simulator operation is not implemented; inspect /sim/capabilities")
