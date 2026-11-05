
import html
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from engine import build_projections, fetch_schedule


# ============================================================
# FROZEN FORECAST — NHL PROJECTION CENTER
# ============================================================

ET = ZoneInfo("America/New_York")
MODEL_VERSION = "v1_goalie_adjusted"

st.set_page_config(
    page_title="Frozen Forecast | NHL Projection Center",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CSS
# ============================================================

st.html("""
<style>
.stApp {
    background: radial-gradient(
        ellipse at 50% -15%,
        #16436b 0%,
        #081726 40%,
        #040d18 100%
    );
    color: #eaf6ff;
}

.block-container {
    max-width: 1700px;
    padding-top: 1.3rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: #eaf6ff !important;
}

.ff-hero {
    border: 1px solid #42baf2;
    border-radius: 16px;
    background: linear-gradient(
        100deg, #081725, #0d3555 52%, #071521
    );
    padding: 17px 24px;
    box-shadow: 0 0 24px #008bff33;
}

.ff-sub {
    font-size: 11px;
    letter-spacing: 3px;
    color: #9adfff;
}

.ff-head {
    font-weight: 1000;
    font-size: clamp(34px, 5vw, 65px);
    line-height: 1.1;
    color: #e9f7ff;
    text-shadow: 0 0 20px #27b9ff99;
}

.ff-head span {
    color: #44c7ff;
}

.ff-panel {
    background: #071c2ee8;
    border: 1px solid #2a95c9;
    border-radius: 13px;
    padding: 15px;
    margin-bottom: 14px;
    box-shadow: 0 0 14px #009dff20;
}

.ff-panel-title {
    font-size: 16px;
    font-weight: 800;
    color: #f0f8ff;






