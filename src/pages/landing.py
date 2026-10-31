"""Public landing page. Opens the guest access card; it does not score telemetry."""

import streamlit as st

from src.session_nav import open_demo_access

_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap');
    section[data-testid="stSidebar"] { display: none; }
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(1000px 480px at 90% -10%, rgba(56, 189, 248, 0.14), transparent 55%),
            radial-gradient(800px 420px at -10% 20%, rgba(124, 58, 237, 0.18), transparent 50%),
            #070b14;
        color: #e2e8f0;
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
    }
    .block-container { padding-top: 1.2rem; max-width: 1180px; }
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(90deg, #0369a1, #22d3ee) !important;
        border: 1px solid rgba(103, 232, 249, 0.7) !important;
        color: #041018 !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        box-shadow: 0 0 18px rgba(34, 211, 238, 0.45);
    }
    h1, h2, h3, .brand { font-family: Sora, "Segoe UI", sans-serif; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.25rem; }
    .brand svg { filter: drop-shadow(0 0 8px rgba(34, 211, 238, 0.65)); }
    .navlinks { display: flex; gap: 22px; align-items: center; justify-content: flex-end; padding-top: 8px; }
    .navlinks a { color: #cbd5e1; text-decoration: none; font-weight: 600; }
    .navlinks a:hover { color: #67e8f9; }
    .kicker { color: #67e8f9; letter-spacing: 0.16em; text-transform: uppercase; font-size: 0.78rem; }
    .hero h1 { font-size: 3.1rem; line-height: 1.08; margin: 0.3rem 0 0.8rem; }
    .hero p.lead { font-size: 1.12rem; color: #cbd5e1; max-width: 640px; }
    .ghost {
        display: inline-block; margin-top: 0.35rem; padding: 0.55rem 1rem;
        border: 1px solid rgba(103, 232, 249, 0.45); border-radius: 999px;
        color: #e0f2fe; text-decoration: none;
    }
    .ghost:hover { box-shadow: 0 0 18px rgba(34, 211, 238, 0.35); }
    .radar {
        position: relative; height: 320px; border-radius: 24px;
        border: 1px solid rgba(103, 232, 249, 0.35);
        background: radial-gradient(circle at 50% 50%, rgba(14, 165, 233, 0.18), rgba(7, 11, 20, 0.2) 62%);
        overflow: hidden; box-shadow: 0 0 40px rgba(14, 165, 233, 0.12);
    }
    .radar .ring, .radar .ring2, .radar .ring3 {
        position: absolute; border: 1px solid rgba(125, 211, 252, 0.35); border-radius: 50%;
        left: 50%; top: 50%; transform: translate(-50%, -50%);
    }
    .radar .ring { width: 90px; height: 90px; }
    .radar .ring2 { width: 170px; height: 170px; }
    .radar .ring3 { width: 250px; height: 250px; }
    .sweep {
        position: absolute; inset: 0;
        background: conic-gradient(from 0deg, transparent 0 78%, rgba(34, 211, 238, 0.35) 92%, transparent 100%);
        animation: spin 4.5s linear infinite;
    }
    .blip {
        position: absolute; width: 8px; height: 8px; border-radius: 50%;
        background: #67e8f9; left: 62%; top: 38%;
        box-shadow: 0 0 12px #22d3ee;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .sim-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .chip {
        border: 1px solid rgba(148, 163, 184, 0.35); border-radius: 999px;
        padding: 4px 10px; font-size: 0.82rem; color: #bae6fd; background: rgba(15, 23, 42, 0.7);
    }
    .chip strong { color: #f8fafc; }
    .grid { display: grid; gap: 14px; }
    .grid.metrics { grid-template-columns: repeat(4, 1fr); }
    .grid.features, .grid.scenarios { grid-template-columns: repeat(3, 1fr); }
    .card {
        border: 1px solid rgba(148, 163, 184, 0.22);
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.88), rgba(7, 11, 20, 0.75));
        border-radius: 16px; padding: 16px 16px 12px;
        transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    }
    .card:hover {
        border-color: rgba(103, 232, 249, 0.7);
        box-shadow: 0 0 22px rgba(34, 211, 238, 0.16);
        transform: translateY(-2px);
    }
    .card h3 { margin: 0 0 6px; font-size: 1.05rem; }
    .card p, .about p { color: #cbd5e1; }
    .metric { font-size: 1.7rem; color: #67e8f9; margin: 0; }
    .flow { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .step {
        border: 1px solid rgba(125, 211, 252, 0.4); border-radius: 12px;
        padding: 10px 12px; background: rgba(8, 47, 73, 0.45);
    }
    .arrow { color: #22d3ee; font-size: 1.2rem; }
    .stack { display: flex; flex-wrap: wrap; gap: 8px; }
    .stack span {
        padding: 8px 12px; border-radius: 999px;
        background: rgba(30, 41, 59, 0.9); border: 1px solid rgba(167, 139, 250, 0.45);
    }
    .section { margin-top: 2.4rem; }
    @media (max-width: 900px) {
        .hero h1 { font-size: 2.2rem; }
        .grid.metrics, .grid.features, .grid.scenarios { grid-template-columns: 1fr; }
    }
</style>
"""

_LOGO = """
<div class="brand">
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 2l7 3v6c0 5-3.2 8.4-7 10-3.8-1.6-7-5-7-10V5l7-3z" stroke="#67e8f9" stroke-width="1.6"/>
    <path d="M12 7v5l3 2" stroke="#a78bfa" stroke-width="1.6" stroke-linecap="round"/>
  </svg>
  FINDR AI
</div>
"""

_NAV = """
<div class="navlinks">
  <a href="#top">Home</a>
  <a href="#features">Features</a>
  <a href="#architecture">Architecture</a>
  <a href="#about">About</a>
</div>
"""

_RADAR = """
<div class="radar" aria-hidden="true">
  <div class="sweep"></div>
  <div class="ring"></div>
  <div class="ring2"></div>
  <div class="ring3"></div>
  <div class="blip"></div>
</div>
<div class="sim-row">
  <span class="chip"><strong>SIMULATED</strong> telemetry</span>
  <span class="chip">Seed 409</span>
  <span class="chip">No RF transmission</span>
</div>
"""

_BODY = """
<div class="section" id="platform">
  <p class="kicker">Platform</p>
  <h2>What this demonstration actually runs</h2>
  <div class="grid metrics">
    <div class="card"><p class="metric">7</p><h3>Simulated delivery scenarios</h3><p>Clean runs, spoofing, drift, jumps, false arrival, route deviation, and suspicious movement. All generated locally.</p></div>
    <div class="card"><p class="metric">2</p><h3>Detection layers</h3><p>Deterministic physics rules first. Rule-based agents explain that label afterward.</p></div>
    <div class="card"><p class="metric">3</p><h3>Investigation agents</h3><p>Signal investigation, delivery risk, and a parcel handoff plan. No language-model API.</p></div>
    <div class="card"><p class="metric">1</p><h3>Human gate</h3><p>A handoff stays pending until an operator approves, rejects, or overrides it.</p></div>
  </div>
</div>
<div class="section" id="features">
  <p class="kicker">Features</p>
  <h2>Capabilities in this build</h2>
  <div class="grid features">
    <div class="card"><h3>GPS spoofing detection</h3><p>Labels a coordinate leap, a slow residual creep, an RF power surge, and a frozen constellation. Multipath stays a separate, non-attack label.</p></div>
    <div class="card"><h3>Deterministic integrity engine</h3><p>Scores 0–100 from step size, speed, acceleration, GNSS versus INS residual, C/N0 mean and variance, and replayed satellite metrics.</p></div>
    <div class="card"><h3>Multi-agent investigation</h3><p>Writes an explainable verdict with confidence, RF notes, the inertial gap, and a synthetic cellular offset. No radio is used.</p></div>
    <div class="card"><h3>Intelligent risk assessment</h3><p>Combines parcel class, GPS fault, vehicle battery, and handoff exposure into a score and a LOW to CRITICAL band.</p></div>
    <div class="card"><h3>Parcel recovery planning</h3><p>Selects the nearest staffed handoff point that still has an open slot, measured from the reference track rather than the reported GPS fix.</p></div>
    <div class="card"><h3>Human authorization</h3><p>Approve, reject, and override are stored with the operator name, notes, and the incident id. A second decision on the same incident is refused.</p></div>
    <div class="card"><h3>Tamper-evident audit history</h3><p>SQLite keeps each frame and a SHA-256 chain. Verification catches an edited row and a deleted tip. Rewriting the chain and the anchor together still verifies.</p></div>
  </div>
</div>
<div class="section" id="architecture">
  <p class="kicker">Architecture</p>
  <h2>From a synthetic frame to a stored decision</h2>
  <div class="flow">
    <div class="step">Synthetic telemetry</div><span class="arrow">→</span>
    <div class="step">GPS integrity engine</div><span class="arrow">→</span>
    <div class="step">Investigation agent</div><span class="arrow">→</span>
    <div class="step">Risk assessment agent</div><span class="arrow">→</span>
    <div class="step">Parcel recovery</div><span class="arrow">→</span>
    <div class="step">Human approval</div><span class="arrow">→</span>
    <div class="step">SQLite audit history</div>
  </div>
</div>
<div class="section" id="scenarios">
  <p class="kicker">Scenarios</p>
  <h2>Seven synthetic deliveries</h2>
  <div class="grid scenarios">
    <div class="card"><h3>Teleportation coordinate jump</h3><p>The reported fix leaps hundreds of meters. Later frames keep that offset and stay labeled a teleport.</p></div>
    <div class="card"><h3>Insidious creeping drift</h3><p>A small bias accumulates. The step stays inside the speed bound while the inertial residual grows.</p></div>
    <div class="card"><h3>High-power RF signal surge</h3><p>Satellite C/N0 saturates and the variance collapses, which is the signature of a nearby synthetic transmitter.</p></div>
    <div class="card"><h3>Constellation replay freeze</h3><p>HDOP, the C/N0 vector, and clock drift repeat for several epochs. One frozen frame is not enough to call it a replay.</p></div>
    <div class="card"><h3>False delivery arrival</h3><p>The report sits on the customer pin while the reference track is still on the road.</p></div>
    <div class="card"><h3>Route deviation</h3><p>The report and the reference track agree, and both leave the planned corridor.</p></div>
    <div class="card"><h3>Suspicious movement</h3><p>The track moves faster than a delivery run without becoming a coordinate teleport.</p></div>
    <div class="card"><h3>Clean nominal delivery</h3><p>Kinematics, signal power, and the reference residual stay inside bounds. The plan is to continue the route.</p></div>
  </div>
</div>
<div class="section">
  <p class="kicker">Stack</p>
  <h2>Technologies in the repository</h2>
  <div class="stack">
    <span>Python</span><span>Streamlit</span><span>Pydantic</span><span>NumPy</span>
    <span>Pandas</span><span>Folium</span><span>SQLite</span><span>Pytest</span>
  </div>
</div>
<div class="section about" id="about">
  <p class="kicker">About</p>
  <h2>A decision loop for a delivery corridor</h2>
  <p>FINDR AI is a local simulation of GPS security for motorcycle, scooter, car, and van deliveries. It separates a bad fix that is still physically plausible from a fix that breaks kinematics or the reference track, then asks a person before a parcel handoff is treated as authorized.</p>
</div>
<div class="section">
  <p class="kicker">Delivery operations</p>
  <h2>Ready to Explore Intelligent Delivery Defense?</h2>
</div>
"""


def _launch() -> None:
    open_demo_access(st.session_state)
    st.rerun()


def render_landing() -> None:
    st.markdown(_STYLE, unsafe_allow_html=True)
    st.markdown('<div id="top"></div>', unsafe_allow_html=True)
    logo, links, launch = st.columns([1.4, 2.4, 1.2])
    with logo:
        st.markdown(_LOGO, unsafe_allow_html=True)
    with links:
        st.markdown(_NAV, unsafe_allow_html=True)
    with launch:
        if st.button("Launch Dashboard", type="primary", key="nav_launch", width="stretch"):
            _launch()

    copy, visual = st.columns([1.25, 1], gap="large")
    with copy:
        st.markdown(
            """
            <div class="hero">
              <p class="kicker">E-commerce delivery security</p>
              <h1>Intelligent GPS Security for Trusted Deliveries.</h1>
              <p class="lead">FINDR AI detects GPS spoofing, suspicious location manipulation, unusual delivery movement, and delivery fraud signals for motorcycle, scooter, car, and van parcels.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        primary, secondary = st.columns(2)
        with primary:
            if st.button("Launch Demo", type="primary", key="hero_launch", width="stretch"):
                _launch()
        with secondary:
            st.markdown('<a class="ghost" href="#platform">Explore Platform</a>', unsafe_allow_html=True)
    with visual:
        st.markdown(_RADAR, unsafe_allow_html=True)

    st.markdown(_BODY, unsafe_allow_html=True)
    if st.button("Launch FINDR Mission Control", type="primary", key="final_launch"):
        _launch()
