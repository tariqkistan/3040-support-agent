"""Microsoft Foundry agent creation and run logic.

Implemented in stage 3. Kept as a module now so app/main.py imports cleanly.
"""

from app.config import Settings


async def run_agent_turn(
    session_id: str, message: str, settings: Settings
) -> tuple[str, list[dict]]:
    """Run one turn of the support agent. Returns (answer, sources)."""
    raise NotImplementedError("Agent is implemented in stage 3.")
