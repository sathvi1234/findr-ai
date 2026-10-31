"""MongoDB document store. Tests use the in-memory store and never need Atlas."""

from datetime import datetime, timezone
from typing import Any, Optional

from src.models import IncidentRecord
from src.persistence.documents import incident_documents, merge_order_status
from src.persistence.env import mongodb_settings
from src.session_nav import DEMO_USER

COLLECTIONS = (
    "users",
    "delivery_agents",
    "delivery_orders",
    "telemetry_frames",
    "anomaly_events",
    "rescue_actions",
    "audit_logs",
)

INDEXES = (
    ("users", [("username", 1)], {"unique": True}),
    ("delivery_agents", [("agent_id", 1)], {"unique": True}),
    ("delivery_agents", [("last_location", "2dsphere")], {}),
    ("delivery_orders", [("order_id", 1)], {"unique": True}),
    ("delivery_orders", [("agent_id", 1), ("updated_at", -1)], {}),
    ("delivery_orders", [("destination", "2dsphere")], {}),
    ("telemetry_frames", [("order_id", 1), ("recorded_at", -1)], {}),
    ("telemetry_frames", [("agent_id", 1), ("recorded_at", -1)], {}),
    ("telemetry_frames", [("location", "2dsphere")], {}),
    ("telemetry_frames", [("reference_location", "2dsphere")], {}),
    ("anomaly_events", [("incident_id", 1)], {"unique": True}),
    ("anomaly_events", [("order_id", 1), ("created_at", -1)], {}),
    ("anomaly_events", [("agent_id", 1), ("created_at", -1)], {}),
    ("rescue_actions", [("incident_id", 1), ("created_at", -1)], {}),
    ("rescue_actions", [("order_id", 1), ("created_at", -1)], {}),
    ("audit_logs", [("order_id", 1), ("created_at", -1)], {}),
    ("audit_logs", [("incident_id", 1), ("created_at", -1)], {}),
    ("audit_logs", [("migration_key", 1)], {"unique": True, "sparse": True}),
)

PAGE_LIMIT_MAX = 100


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    safe_limit = min(max(int(limit), 1), PAGE_LIMIT_MAX)
    safe_offset = min(max(int(offset), 0), 10_000)
    return safe_limit, safe_offset


class MemoryFindrStore:
    """Same documents as MongoDB, for unit tests and a demo with no Atlas URI."""

    def __init__(self) -> None:
        self.documents: dict[str, list[dict]] = {name: [] for name in COLLECTIONS}
        self.kind = "memory"
        self.seed_demo_user()

    def seed_demo_user(self) -> dict:
        existing = self.find_one("users", "username", "demo")
        if existing:
            return existing
        document = {
            "username": "demo",
            "name": DEMO_USER["name"],
            "role": DEMO_USER["role"],
            "access": DEMO_USER["access"],
            "authentication": DEMO_USER["authentication"],
            "created_at": datetime.now(timezone.utc),
        }
        self.documents["users"].append(document)
        return document

    def ensure_indexes(self) -> None:
        return None

    def find_one(self, collection: str, key: str, value: Any) -> Optional[dict]:
        for row in self.documents[collection]:
            if row.get(key) == value:
                return row
        return None

    def upsert(self, collection: str, key: str, value: Any, document: dict) -> dict:
        rows = self.documents[collection]
        for index, row in enumerate(rows):
            if row.get(key) == value:
                rows[index] = document
                return document
        rows.append(document)
        return document

    def insert_new(self, collection: str, key: str, value: Any, document: dict) -> bool:
        if value is not None and self.find_one(collection, key, value):
            return False
        self.documents[collection].append(document)
        return True

    def save_incident(self, record: IncidentRecord) -> None:
        docs = incident_documents(record)
        agent = docs["agent"]
        self.upsert("delivery_agents", "agent_id", agent["agent_id"], {
            **(self.find_one("delivery_agents", "agent_id", agent["agent_id"]) or {}),
            **agent,
        })
        order = docs["order"]
        previous = self.find_one("delivery_orders", "order_id", order["order_id"]) or {}
        order["status"] = merge_order_status(previous.get("status"), order["status"])
        self.upsert("delivery_orders", "order_id", order["order_id"], {**previous, **order})
        self.insert_new("telemetry_frames", "incident_id", docs["telemetry"]["incident_id"], docs["telemetry"])
        self.insert_new("anomaly_events", "incident_id", docs["anomaly"]["incident_id"], docs["anomaly"])
        if docs["rescue"] is not None:
            self.insert_new("rescue_actions", "incident_id", docs["rescue"]["incident_id"], docs["rescue"])
        self.insert_new("audit_logs", "incident_id", docs["audit"]["incident_id"], docs["audit"])

    def save_decision(
        self,
        incident_id: str,
        order_id: str,
        agent_id: str,
        approval_status: str,
        operator_name: str,
        execution_status: str,
        decided_at: float,
    ) -> None:
        self.documents["rescue_actions"].append({
            "incident_id": incident_id,
            "order_id": order_id,
            "agent_id": agent_id,
            "approval_status": approval_status,
            "operator_name": operator_name,
            "execution_status": execution_status,
            "event_type": "operator_decision",
            "created_at": datetime.fromtimestamp(decided_at, tz=timezone.utc),
            "source": "pipeline",
        })
        self.documents["audit_logs"].append({
            "source": "pipeline",
            "event_type": "decision",
            "incident_id": incident_id,
            "order_id": order_id,
            "agent_id": agent_id,
            "approval_status": approval_status,
            "operator_name": operator_name,
            "created_at": datetime.fromtimestamp(decided_at, tz=timezone.utc),
            "note": "SHA-256 chain for this decision stays in the SQLite audit log.",
        })

    def query(
        self,
        collection: str,
        filters: Optional[dict] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        limit, offset = clamp_page(limit, offset)
        filters = {key: value for key, value in (filters or {}).items() if value is not None}
        matched = [
            row for row in self.documents[collection]
            if all(row.get(key) == value for key, value in filters.items())
        ]
        matched.sort(key=lambda row: row.get("created_at") or row.get("updated_at") or row.get("recorded_at") or "", reverse=True)
        return {
            "items": matched[offset:offset + limit],
            "total": len(matched),
            "limit": limit,
            "offset": offset,
        }


class MongoFindrStore:
    """PyMongo store. One client is created at startup and reused."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.kind = "mongodb"
        self.ensure_indexes()
        self.seed_demo_user()

    def seed_demo_user(self) -> dict:
        document = {
            "username": "demo",
            "name": DEMO_USER["name"],
            "role": DEMO_USER["role"],
            "access": DEMO_USER["access"],
            "authentication": DEMO_USER["authentication"],
            "created_at": datetime.now(timezone.utc),
        }
        self.database["users"].update_one({"username": "demo"}, {"$setOnInsert": document}, upsert=True)
        return self.find_one("users", "username", "demo") or document

    def ensure_indexes(self) -> None:
        for collection, keys, options in INDEXES:
            self.database[collection].create_index(keys, **options)

    def find_one(self, collection: str, key: str, value: Any) -> Optional[dict]:
        return self.database[collection].find_one({key: value}, {"_id": 0})

    def upsert(self, collection: str, key: str, value: Any, document: dict) -> dict:
        stored = {k: v for k, v in document.items() if k != "_id"}
        self.database[collection].replace_one({key: value}, stored, upsert=True)
        return stored

    def insert_new(self, collection: str, key: str, value: Any, document: dict) -> bool:
        if value is not None and self.find_one(collection, key, value):
            return False
        self.database[collection].insert_one(dict(document))
        return True

    def save_incident(self, record: IncidentRecord) -> None:
        docs = incident_documents(record)
        agent = docs["agent"]
        self.database["delivery_agents"].update_one(
            {"agent_id": agent["agent_id"]},
            {"$set": agent},
            upsert=True,
        )
        order = docs["order"]
        previous = self.find_one("delivery_orders", "order_id", order["order_id"]) or {}
        order["status"] = merge_order_status(previous.get("status"), order["status"])
        self.database["delivery_orders"].update_one(
            {"order_id": order["order_id"]},
            {"$set": order},
            upsert=True,
        )
        self._insert_unless(docs["telemetry"], "telemetry_frames", "incident_id")
        self._insert_unless(docs["anomaly"], "anomaly_events", "incident_id")
        if docs["rescue"] is not None:
            self._insert_unless(docs["rescue"], "rescue_actions", "incident_id")
        audit = docs["audit"]
        audit["migration_key"] = f"pipeline:{audit['incident_id']}"
        self._insert_unless(audit, "audit_logs", "migration_key")

    def _insert_unless(self, document: dict, collection: str, key: str) -> None:
        self.database[collection].update_one(
            {key: document[key]},
            {"$setOnInsert": document},
            upsert=True,
        )

    def save_decision(
        self,
        incident_id: str,
        order_id: str,
        agent_id: str,
        approval_status: str,
        operator_name: str,
        execution_status: str,
        decided_at: float,
    ) -> None:
        created_at = datetime.fromtimestamp(decided_at, tz=timezone.utc)
        key = f"decision:{incident_id}:{approval_status}:{decided_at}"
        self.database["rescue_actions"].update_one(
            {"migration_key": key},
            {"$setOnInsert": {
                "migration_key": key,
                "incident_id": incident_id,
                "order_id": order_id,
                "agent_id": agent_id,
                "approval_status": approval_status,
                "operator_name": operator_name,
                "execution_status": execution_status,
                "event_type": "operator_decision",
                "created_at": created_at,
                "source": "pipeline",
            }},
            upsert=True,
        )
        self.database["audit_logs"].update_one(
            {"migration_key": f"audit-{key}"},
            {"$setOnInsert": {
                "migration_key": f"audit-{key}",
                "source": "pipeline",
                "event_type": "decision",
                "incident_id": incident_id,
                "order_id": order_id,
                "agent_id": agent_id,
                "approval_status": approval_status,
                "operator_name": operator_name,
                "created_at": created_at,
                "note": "SHA-256 chain for this decision stays in the SQLite audit log.",
            }},
            upsert=True,
        )

    def query(
        self,
        collection: str,
        filters: Optional[dict] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        limit, offset = clamp_page(limit, offset)
        query = {key: value for key, value in (filters or {}).items() if value is not None}
        cursor = (
            self.database[collection]
            .find(query, {"_id": 0})
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return {
            "items": list(cursor),
            "total": self.database[collection].count_documents(query),
            "limit": limit,
            "offset": offset,
        }


def selection_timeout_ms(uri: str) -> int:
    """Atlas SRV lookups need longer than a local refused connection."""
    if uri.startswith("mongodb+srv://"):
        return 8000
    return 800


def open_document_store(uri: Optional[str] = None, database_name: Optional[str] = None):
    """Connect when MONGODB_URI is set. Otherwise report that Atlas is not configured."""
    configured, default_db = mongodb_settings()
    chosen = uri if uri is not None else configured
    name = database_name or default_db
    if not chosen or chosen == "memory":
        return None, "unconfigured"
    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError

        client = MongoClient(chosen, serverSelectionTimeoutMS=selection_timeout_ms(chosen))
        client.admin.command("ping")
        return MongoFindrStore(client[name]), "mongodb"
    except PyMongoError:
        return None, "unavailable"
    except Exception:
        return None, "unavailable"
