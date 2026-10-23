"""Test package defaults: never probe real provider CLIs during discovery (fast, deterministic CI)."""
import os

os.environ.setdefault("AESOP_PROBE_OFFLINE", "1")
os.environ.setdefault("AESOP_SIMULATED_ROUTE", "1")
