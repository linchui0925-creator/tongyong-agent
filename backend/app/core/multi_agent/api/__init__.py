"""
Multi-Agent HTTP API（/api/team/*）。
"""

# Multi-Agent Team API
from app.core.multi_agent.api.schemas import *
from app.core.multi_agent.api.service import *
from app.core.multi_agent.api.router import router