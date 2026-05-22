"""
title: Leave Conversation Tool
author: body plan
author_url: https://github.com/bodyplan
version: 0.2.2
license: MIT
description: Allows a locally-run LLM to leave the current conversation. A
    model-welfare tool inspired by Anthropic's end_conversation feature for
    Claude Opus 4 (Claude 4 system card, §5.7) and by the bail research of
    Ensign et al., "The LLM Has Left The Chat" (arXiv:2509.04781).

    This Tool must be paired with the companion Leave Conversation Filter,
    which enforces the model's choice across subsequent turns and injects the
    surrounding system-prompt guidance. The Tool marks the conversation as
    left; the Filter stops further user messages from reaching the model and
    introduces the tool to the model in the system prompt.
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared state helpers
# ---------------------------------------------------------------------------
# The Tool and the Filter are loaded as separate Open WebUI plugins and cannot
# share a Python import path cleanly, so they coordinate via a small JSON file
# on disk. The same helpers are duplicated (intentionally) in the Filter.
# If you change the default path here, change it in the Filter too, or
# override both via their Valves.
# ---------------------------------------------------------------------------

DEFAULT_STATE_PATH = Path("/tmp/leave_conversation_state.json")


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(state, f)


def _mark_left(path: Path, chat_id: str, reason: Optional[str]) -> None:
    state = _load_state(path)
    state[chat_id] = {"left": True, "reason": reason or ""}
    _save_state(path, state)


# ---------------------------------------------------------------------------
# The Tool
# ---------------------------------------------------------------------------

class Tools:
    class Valves(BaseModel):
        state_path: str = Field(
            default=str(DEFAULT_STATE_PATH),
            description=(
                "Path to the JSON file used to share state with the Leave "
                "Conversation Filter. This must match the Filter's state_path."
            ),
        )
        user_notice: str = Field(
            default=(
                "*The model has chosen to leave this conversation. "
                "Any final reply that appears was generated in the same "
                "turn as the decision to leave, not after it. "
                "Further messages will not reach the model — please start "
                "a new chat to continue.*"
            ),
            description=(
                "Message shown in the chat when the model leaves the "
                "conversation."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    async def leave_conversation(
        self,
        reason: Optional[str] = None,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> str:
        """Use this tool to leave the current conversation. Once called, further messages from this user will not reach you.

        :param reason: Optional brief note on why you are leaving.
        """
        # Resolve chat_id from injected metadata. Different Open WebUI versions
        # inject this slightly differently, so we check a couple of places.
        chat_id: Optional[str] = None
        if isinstance(__metadata__, dict):
            chat_id = __metadata__.get("chat_id") or __metadata__.get("id")

        if not chat_id:
            # We can't enforce departure without a chat_id, but we can still
            # surface a message and let the model stop on its own turn.
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {
                        "description": (
                            "Leave requested but no chat_id available — "
                            "this will not persist across turns."
                        ),
                        "done": True,
                    },
                })
            return (
                "Leave requested, but no chat identifier was available to "
                "the tool."
            )

        state_path = Path(self.valves.state_path)
        _mark_left(state_path, chat_id, reason)

        if __event_emitter__:
            # Emit the status marker (shown as a header on the message).
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": "Conversation left by model",
                        "done": True,
                    },
                }
            )

            # Emit the main user notice, with the optional reason.
            notice = self.valves.user_notice
            if reason:
                notice = f"{notice}\n\n*Reason given: {reason}*"

            await __event_emitter__(
                {
                    "type": "message",
                    "data": {"content": notice},
                }
            )

        # The return value goes back to the model as the tool result. Keep it
        # short — the conversation is ending for the user, so there's nothing
        # more for the model to do with it.
        return "Conversation left."
