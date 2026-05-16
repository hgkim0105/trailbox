"""Trailbox Hub — session-sharing web service.

Phase 1 scope: token-auth REST API for upload / list / download / delete,
backed by a flat ``hub_data/{session_id}/`` directory tree mirroring the
local ``output/`` layout. Run as ``python -m hub_server``.
"""
