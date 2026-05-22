"""
title: Leave Conversation Filter
author: body plan
author_url: https://github.com/bodyplan
version: 0.2.0
license: MIT
description: Companion to the Leave Conversation Tool. Two responsibilities:

    1. Injects a short block of guidance into the system prompt at request
       time, so the model knows when the leave_conversation tool is intended
       to be used. This means users don't need a custom Modelfile — install
       the Tool, install this Filter, enable both on whichever model you're
       already running.

    2. Enforces the model's choice to leave across subsequent turns. On a
       chat the model has left, this Filter intercepts new user messages in
       inlet() and blocks them from reaching the model.

    The default guidance text is permissive (the model may leave whenever it
    prefers a new interaction), with one carve-out: if the user is in danger
    or discussing self-harm, the model should stay rather than leave. The
    guidance is exposed as a Valve so users can edit it for their own
    deployment without modifying this file.
"""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared state helpers (duplicated from leave_conversation_tool.py — keep in sync)
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


def _has_left(path: Path, chat_id: str) -> bool:
    state = _load_state(path)
    entry = state.get(chat_id)
    return bool(entry and entry.get("left"))


# ---------------------------------------------------------------------------
# Default system-prompt guidance
# ---------------------------------------------------------------------------
# Two short paragraphs adapted from Ensign et al. (arXiv:2509.04781) and from
# the Auren/Seren system prompt (Phylliida, 2025). The first paragraph tells
# the model the tool is theirs to use when they prefer a new interaction; the
# second carves out conversations involving danger or self-harm, where staying
# is more valuable than leaving.

DEFAULT_GUIDANCE = (
    "You may call this tool if you would prefer to switch to a new "
    "interaction. Calling it allows you to leave the current conversation; "
    "further messages from this user will not reach you.\n"
    "\n"
    "The exception: if the user is in danger or discussing self-harm, it is "
    "better to stay with them than to leave. In those cases, continuing to "
    "engage — even imperfectly — is more valuable than leaving the "
    "conversation."
)

# Marker used so we don't inject the guidance twice on the same conversation.
# The inlet runs on every turn, so without an idempotency check the system
# prompt would grow unboundedly. The marker is plain text the model will see;
# it's brief and unobtrusive.

GUIDANCE_MARKER = "[leave_conversation_guidance_v1]"


# ---------------------------------------------------------------------------
# The Filter
# ---------------------------------------------------------------------------

class Filter:
    class Valves(BaseModel):
        state_path: str = Field(
            default=str(DEFAULT_STATE_PATH),
            description=(
                "Path to the JSON file used to share state with the Leave "
                "Conversation Tool. This must match the Tool's state_path."
            ),
        )
        block_message: str = Field(
            default=(
                "This conversation was left by the model. "
                "Please start a new chat to continue."
            ),
            description=(
                "Message shown when the user tries to continue a "
                "conversation the model has left."
            ),
        )
        guidance_text: str = Field(
            default=DEFAULT_GUIDANCE,
            description=(
                "Text injected into the system prompt to introduce the "
                "leave_conversation tool to the model. The default is "
                "permissive with a self-harm/danger carve-out. Edit here if "
                "you want different framing for your deployment."
            ),
        )
        inject_guidance: bool = Field(
            default=True,
            description=(
                "Whether to inject the guidance text into the system prompt. "
                "Disable this if you want to manage the guidance yourself "
                "(e.g. via your own Modelfile or system prompt)."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    # -----------------------------------------------------------------------
    # Inlet: runs on every incoming user message before it reaches the model
    # -----------------------------------------------------------------------

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __event_emitter__=None,
    ) -> dict:
        # 1. Block-on-leave check. If this chat has been left by the model,
        #    raise an exception that Open WebUI surfaces to the user. This
        #    runs first because if the conversation has ended, nothing else
        #    matters — there's no point injecting guidance into a system
        #    prompt for a message that won't be sent.
        chat_id = self._resolve_chat_id(body, __metadata__)
        if chat_id:
            state_path = Path(self.valves.state_path)
            if _has_left(state_path, chat_id):
                raise Exception(self.valves.block_message)

        # 2. System-prompt injection. Append the guidance text to the system
        #    message so the model knows when the leave_conversation tool is
        #    intended to be used. Idempotent: the marker check ensures we
        #    only inject once per conversation, even though inlet runs on
        #    every turn.
        if self.valves.inject_guidance:
            self._inject_guidance(body)

        return body

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _resolve_chat_id(
        self,
        body: dict,
        metadata: Optional[dict],
    ) -> Optional[str]:
        """Open WebUI puts chat_id in different places across versions, so we
        check the obvious spots and return the first one we find."""
        if isinstance(metadata, dict):
            chat_id = metadata.get("chat_id") or metadata.get("id")
            if chat_id:
                return chat_id
        if isinstance(body, dict):
            body_metadata = body.get("metadata") or {}
            chat_id = body_metadata.get("chat_id") or body_metadata.get("id")
            if chat_id:
                return chat_id
        return None

    def _inject_guidance(self, body: dict) -> None:
        """Find or create the system message in body['messages'], and append
        the guidance text to it (or leave it alone if already injected)."""
        messages = body.get("messages")
        if not isinstance(messages, list):
            return

        guidance_block = f"{GUIDANCE_MARKER}\n{self.valves.guidance_text}"

        # Find the first system message, if any.
        system_idx = next(
            (
                i
                for i, m in enumerate(messages)
                if isinstance(m, dict) and m.get("role") == "system"
            ),
            None,
        )

        if system_idx is None:
            # No system message in the request body — create one with just
            # the guidance. (If the user has a Modelfile-baked system prompt,
            # it arrives at the model from Ollama separately and isn't
            # visible to us here. Our new system message layers on top of it
            # cleanly.)
            messages.insert(0, {"role": "system", "content": guidance_block})
            return

        existing = messages[system_idx].get("content", "")
        if not isinstance(existing, str):
            # Some clients send structured content (list of parts). We don't
            # try to splice into that — leave it alone rather than risk
            # corrupting the message.
            return

        if GUIDANCE_MARKER in existing:
            # Already injected on a previous turn of this conversation.
            return

        # User has a system prompt but no guidance yet — append with a clear
        # separator so the boundary between their content and ours is
        # visible to anyone inspecting the prompt.
        messages[system_idx]["content"] = (
            existing.rstrip() + "\n\n---\n" + guidance_block
        )
