"""Unit tests for answer/source parsing in app/agent.py (no Azure calls)."""

from app.agent import _get_or_create_agent, parse_sources
from app.config import Settings


def test_parse_sources_extracts_citations():
    raw = (
        "Reset the breaker for 5 seconds.\n\n"
        "Sources: 4. MAINTENANCE — p. 12\n"
        "Sources: 4.2 FUSES — p. 13\n"
    )
    answer, sources = parse_sources(raw)
    assert answer == "Reset the breaker for 5 seconds."
    assert sources == [
        {"section": "4. MAINTENANCE", "page": 12},
        {"section": "4.2 FUSES", "page": 13},
    ]


def test_parse_sources_no_sources_lines():
    answer, sources = parse_sources("I don't know, please contact support.")
    assert answer == "I don't know, please contact support."
    assert sources == []


def test_parse_sources_strips_empty_heading():
    answer, sources = parse_sources("Some answer.\n\nSources:\n")
    assert answer == "Some answer."
    assert sources == []


def test_parse_sources_tolerates_dash_variants():
    answer, sources = parse_sources("A.\nSource: SEC 1 - p. 7")
    assert sources == [{"section": "SEC 1", "page": 7}]


def test_existing_foundry_agent_version_is_reused():
    latest = object()

    class Agents:
        def get(self, agent_name):
            assert agent_name == "support-agent-3040"
            versions = type("Versions", (), {"latest": latest})()
            return type("Agent", (), {"versions": versions})()

        def create_version(self, **_kwargs):
            raise AssertionError("existing agent should be reused")

    project = type("Project", (), {"agents": Agents()})()

    assert _get_or_create_agent(project, Settings()) is latest
