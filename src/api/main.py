"""FastAPI service. Routes are sync functions so PyMongo does not block the event loop."""

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.audit_db import default_audit_path
from src.models import DroneMissionState
from src.persistence.env import load_env_file
from src.persistence.migrate import migrate_sqlite
from src.persistence.store import open_document_store
from src.session_nav import DEMO_USER


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def create_app(store=None, audit_db=None, demo_token: Optional[str] = None) -> FastAPI:
    """Build the API. Tests pass a memory store so Atlas is not required."""
    load_env_file()
    app = FastAPI(title="FINDR AI", version="0.1.0")
    origins = [item.strip() for item in os.environ.get("FINDR_CORS_ORIGINS", "").split(",") if item.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )
    if store is None:
        store, kind = open_document_store()
    else:
        kind = getattr(store, "kind", "memory")
    app.state.store = store
    app.state.store_kind = kind
    app.state.audit_db = audit_db
    token = demo_token if demo_token is not None else os.environ.get("DEMO_API_TOKEN", "")

    def require_demo(authorization: Optional[str] = Header(default=None)) -> dict:
        if not token:
            raise HTTPException(status_code=503, detail="Set DEMO_API_TOKEN before calling the API.")
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Demo access required.")
        if DEMO_USER["role"] != "Delivery Operations Operator":
            raise HTTPException(status_code=403, detail="This role cannot use the delivery API.")
        return dict(DEMO_USER)

    def require_store():
        if app.state.store is None:
            raise HTTPException(
                status_code=503,
                detail="MongoDB is not connected. Set MONGODB_URI and check the Atlas network access list.",
            )
        return app.state.store

    @app.get("/health")
    def health():
        audit_path = default_audit_path()
        return {
            "status": "ok" if app.state.store is not None else "degraded",
            "mongodb": app.state.store_kind,
            "database": os.environ.get("MONGODB_DB", "findr_ai"),
            "audit_file_present": audit_path.is_file(),
        }

    @app.post("/auth/demo")
    def demo_login(user: dict = Depends(require_demo)):
        return {"user": user, "token_type": "bearer"}

    @app.get("/users")
    def list_users(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("users", limit=limit, offset=offset))

    @app.get("/delivery-agents")
    def list_agents(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        agent_id: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("delivery_agents", {"agent_id": agent_id}, limit, offset))

    @app.get("/delivery-orders")
    def list_orders(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        order_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("delivery_orders", {"order_id": order_id, "agent_id": agent_id}, limit, offset))

    @app.get("/telemetry-frames")
    def list_telemetry(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        order_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("telemetry_frames", {"order_id": order_id, "agent_id": agent_id}, limit, offset))

    @app.get("/anomaly-events")
    def list_anomalies(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        order_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        anomaly_type: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query(
            "anomaly_events",
            {"order_id": order_id, "agent_id": agent_id, "anomaly_type": anomaly_type},
            limit,
            offset,
        ))

    @app.get("/rescue-actions")
    def list_rescues(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        order_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("rescue_actions", {"order_id": order_id, "incident_id": incident_id}, limit, offset))

    @app.get("/audit-logs")
    def list_audit(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
        order_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        return _jsonable(store.query("audit_logs", {"order_id": order_id, "incident_id": incident_id}, limit, offset))

    @app.post("/telemetry")
    def ingest_telemetry(
        state: DroneMissionState,
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        from src.audit_db import AuditDatabase
        from src.orchestrator import IncidentOrchestrator

        database = app.state.audit_db or AuditDatabase()
        orchestrator = IncidentOrchestrator(database, document_store=store)
        record = orchestrator.process_frame(state)
        return {
            "incident_id": record.incident_id,
            "order_id": record.order_id,
            "agent_id": record.agent_id,
            "anomaly_type": record.integrity.primary_anomaly.value,
            "anomaly_score": record.integrity.anomaly_score,
            "is_anomalous": record.integrity.is_anomalous,
        }

    @app.post("/admin/migrate-sqlite")
    def migrate(
        store=Depends(require_store),
        user: dict = Depends(require_demo),
    ):
        del user
        from pathlib import Path
        return migrate_sqlite(store, default_audit_path())

    return app


app = create_app()
