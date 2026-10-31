"""
FINDR AI entry point.

Landing page, guest demo access, then the existing mission-control dashboard.
"""

import streamlit as st

from src.audit_db import AuditDatabase
from src.orchestrator import IncidentOrchestrator
from src.persistence.env import load_env_file
from src.persistence.store import open_document_store
from src.pages.auth import render_auth
from src.pages.dashboard import render_dashboard
from src.pages.landing import render_landing
from src.rescue_workflow import RescueWorkflowManager
from src.session_nav import ACCESS, DASHBOARD, LANDING, ensure_nav, resolve_view

st.set_page_config(
    page_title="FINDR AI — Intelligent GPS Security for Trusted Deliveries",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_env_file()
if "audit_db" not in st.session_state:
    st.session_state.audit_db = AuditDatabase()
if "document_store" not in st.session_state:
    store, kind = open_document_store()
    st.session_state.document_store = store
    st.session_state.document_store_kind = kind
# Bind the pipeline on every rerun. A session-cached orchestrator keeps the
# class objects from the first import, and a later module reload then rejects
# new telemetry as the wrong DroneMissionState.
st.session_state.orchestrator = IncidentOrchestrator(
    st.session_state.audit_db,
    document_store=st.session_state.document_store,
)
st.session_state.workflow_manager = RescueWorkflowManager(
    st.session_state.audit_db,
    st.session_state.document_store,
)
ensure_nav(st.session_state)
if "last_records" not in st.session_state:
    st.session_state.last_records = []
if "current_frame_idx" not in st.session_state:
    st.session_state.current_frame_idx = 0
if "active_scenario" not in st.session_state:
    st.session_state.active_scenario = None

view = resolve_view(st.session_state)
if view == LANDING:
    render_landing()
elif view == ACCESS:
    render_auth()
elif view == DASHBOARD:
    render_dashboard()
