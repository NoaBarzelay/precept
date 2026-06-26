"""Isolation seam for fast-moving host integrations (currently Claude Code).

All knowledge of the host's hook wire-format lives behind this package so a host
contract change is a one-file fix. CI fixtures pin the shapes; on an unknown shape
the hooks FAIL OPEN (never block the user because Precept couldn't parse an event).
"""
