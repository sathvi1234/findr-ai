"""MongoDB document copy, pagination, and the FastAPI demo gate."""

from fastapi.testclient import TestClient

from src.api.main import create_app
from src.audit_db import AuditDatabase
from src.models import AnomalyType
from src.orchestrator import IncidentOrchestrator
from src.persistence.documents import merge_order_status
from src.persistence.migrate import migrate_sqlite
from src.persistence.store import INDEXES, MemoryFindrStore
from src.simulator import ScenarioSimulator


def test_indexes_cover_geojson_agents_orders_and_time():
    keys = {(collection, tuple(fields)) for collection, fields, _options in INDEXES}
    assert ("telemetry_frames", (("location", "2dsphere"),)) in keys
    assert ("delivery_orders", (("destination", "2dsphere"),)) in keys
    assert ("delivery_agents", (("agent_id", 1),)) in keys
    assert ("anomaly_events", (("order_id", 1), ("created_at", -1))) in keys
    assert ("audit_logs", (("incident_id", 1), ("created_at", -1))) in keys


def test_pipeline_copy_keeps_longitude_first_and_meeting_status(tmp_path):
    store = MemoryFindrStore()
    store.upsert("delivery_orders", "order_id", "ORD-2026-409", {
        "order_id": "ORD-2026-409",
        "status": "MEETING_REQUESTED",
    })
    state = ScenarioSimulator(mission_id="ORD-2026-409", drone_id="FINDR-AGENT-07").generate_scenario_stream(
        AnomalyType.NONE, total_steps=2, seed=409,
    )[0]
    database = AuditDatabase(db_path=tmp_path / "audit.db")
    record = IncidentOrchestrator(database, document_store=store).process_frame(state)
    frame = store.find_one("telemetry_frames", "incident_id", record.incident_id)
    longitude, latitude = frame["location"]["coordinates"]
    assert longitude == state.reported_gps.longitude
    assert latitude == state.reported_gps.latitude
    assert store.find_one("anomaly_events", "incident_id", record.incident_id)["anomaly_type"] == "NONE"
    assert store.find_one("delivery_orders", "order_id", "ORD-2026-409")["status"] == "MEETING_REQUESTED"
    assert merge_order_status("HANDED_OVER_AT_MEETING_POINT", "IN_TRANSIT") == "HANDED_OVER_AT_MEETING_POINT"


def test_sqlite_migration_copies_chain_and_can_be_repeated(tmp_path):
    database = AuditDatabase(db_path=tmp_path / "findr_audit.db")
    state = ScenarioSimulator().generate_scenario_stream(AnomalyType.NONE, total_steps=1, seed=3)[0]
    IncidentOrchestrator(database).process_frame(state)
    intact, problems = database.verify_integrity()
    assert intact, problems
    store = MemoryFindrStore()
    first = migrate_sqlite(store, tmp_path / "findr_audit.db")
    second = migrate_sqlite(store, tmp_path / "findr_audit.db")
    assert first["incidents"] == 1
    assert first["chain_events"] >= 1
    assert second["incidents"] == 0
    assert second["skipped"] >= 1
    intact_after, problems_after = database.verify_integrity()
    assert intact_after, problems_after
    copied = store.query("audit_logs", {"source": "sqlite_migration"}, limit=20)
    assert any(item.get("event_hash") for item in copied["items"])


def test_api_requires_the_demo_operator_and_scores_a_real_frame(tmp_path):
    store = MemoryFindrStore()
    database = AuditDatabase(db_path=tmp_path / "api.db")
    app = create_app(store=store, audit_db=database, demo_token="demo-test-token")
    client = TestClient(app)
    assert client.get("/health").json()["mongodb"] == "memory"
    assert client.get("/users").status_code == 401
    headers = {"Authorization": "Bearer demo-test-token"}
    profile = client.post("/auth/demo", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["user"]["role"] == "Delivery Operations Operator"
    state = ScenarioSimulator().generate_scenario_stream(AnomalyType.NONE, total_steps=1, seed=11)[0]
    scored = client.post("/telemetry", headers=headers, json=state.model_dump(mode="json"))
    assert scored.status_code == 200
    body = scored.json()
    assert body["anomaly_type"] == "NONE"
    assert body["is_anomalous"] is False
    page = client.get("/telemetry-frames", headers=headers, params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 1
    assert payload["limit"] == 1
    assert payload["items"][0]["location"]["type"] == "Point"
    users = client.get("/users", headers=headers).json()
    assert users["total"] == 1
    assert users["items"][0]["username"] == "demo"
