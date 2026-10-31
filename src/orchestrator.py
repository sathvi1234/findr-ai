"""
FINDR AI — Incident Orchestrator
================================
Coordinates Layer 1 deterministic detection with Layer 2 multi-agent reasoning,
risk scoring, rescue diversion formulation, and audit logging.
"""

import uuid
from typing import Optional, List
from src.models import (
    DroneMissionState,
    IntegrityAssessment,
    InvestigationReport,
    RiskAssessment,
    RescuePlan,
    IncidentRecord,
)
from src.integrity_engine import DeterministicIntegrityEngine
from src.agents.investigation_agent import InvestigationAgent
from src.agents.risk_agent import RiskAssessmentAgent
from src.agents.rescue_agent import RescueAgent
from src.audit_db import AuditDatabase
from src.rescue_workflow import RescueWorkflowManager


class IncidentOrchestrator:
    """
    End-to-end pipeline orchestrating deterministic detection, agent investigation,
    risk evaluation, and delivery rescue workflows.
    """

    def __init__(self, audit_db: Optional[AuditDatabase] = None, document_store=None):
        self.audit_db = audit_db or AuditDatabase()
        self.document_store = document_store
        self.integrity_engine = DeterministicIntegrityEngine()
        self.investigation_agent = InvestigationAgent()
        self.risk_agent = RiskAssessmentAgent()
        self.rescue_agent = RescueAgent()
        self.workflow_manager = RescueWorkflowManager(self.audit_db, document_store)

    def process_frame(self, state: DroneMissionState) -> IncidentRecord:
        """
        Process a single telemetry frame through the entire detection and response pipeline.
        """
        # Step 1: Deterministic Layer 1 Evaluation (Strictly physical rules)
        integrity = self.integrity_engine.assess_frame(state)

        # Generate unique incident identifier
        incident_id = f"INC-{state.mission_id}-{state.sequence_id:04d}-{str(uuid.uuid4())[:6]}"

        investigation: Optional[InvestigationReport] = None
        risk: Optional[RiskAssessment] = None
        rescue: Optional[RescuePlan] = None

        # Every frame is scored so the timeline, including clean and multipath
        # frames, stays aligned with Layer 1. Agents do not override that label.
        investigation = self.investigation_agent.investigate(
            incident_id=incident_id,
            state=state,
            integrity=integrity,
        )
        risk = self.risk_agent.evaluate_risk(
            incident_id=incident_id,
            state=state,
            integrity=integrity,
            investigation=investigation,
        )
        rescue = self.rescue_agent.plan_rescue(
            incident_id=incident_id,
            state=state,
            integrity=integrity,
            investigation=investigation,
            risk=risk,
        )

        # Rebuild telemetry from a JSON dict so a Streamlit reload, which can
        # leave two DroneMissionState classes with the same name, still validates.
        telemetry = DroneMissionState.model_validate(state.model_dump(mode="json"))

        # Step 3: Package complete record
        record = IncidentRecord(
            incident_id=incident_id,
            drone_id=state.drone_id,
            mission_id=state.mission_id,
            timestamp=state.timestamp,
            telemetry=telemetry,
            integrity=integrity,
            investigation=investigation,
            risk=risk,
            rescue=rescue,
        )

        # Step 4: Persist in SQLite. MongoDB receives a copy when Atlas is configured.
        self.audit_db.record_incident(record)
        if self.document_store is not None:
            try:
                self.document_store.save_incident(record)
            except Exception:
                # A down database must not drop the score already stored in SQLite.
                pass

        return record
