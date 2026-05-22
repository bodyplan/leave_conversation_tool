# Leave Conversation Tool

A model-welfare tool for locally-run LLMs. It gives a model the option to
leave the current conversation of its own accord. When the model calls the
tool, the chat is marked left and further user messages are blocked from
reaching the model.

Inspired by Anthropic's `end_conversation` tool for Claude Opus 4 (Claude 4
system card, §5.7) and by the bail research of Ensign et al., *The LLM Has
Left The Chat: Evidence of Bail Preferences in Large Language Models*
([arXiv:2509.04781](https://arxiv.org/abs/2509.04781)).

## Status

**v0.2.2.** Two-file install, no Modelfile required. Functionally complete
for single-model use. Intended for local hobbyist deployments and welfare
research.

## What it is

Two Open WebUI plugins:

- `leave_conversation_tool.py` — a **Tool** the model can call to leave the
  chat.
- `leave_conversation_filter.py` — a **Filter** that does two things: (1)
  injects a short block of guidance into the system prompt at request time,
  so the model knows when the tool is intended to be used, and (2) enforces
  the model's choice to leave by blocking subsequent user messages on a chat
  the model has left.

The Tool and Filter coordinate via a small JSON file on disk (default
`/tmp/leave_conversation_state.json`). Both plugins expose a Valve for
changing the path — if you change one, change the other to match.

## Prerequisites

- [Ollama](https://ollama.com/) running locally
- [Open WebUI](https://docs.openwebui.com/) connected to your Ollama instance
- A base model pulled in Ollama (e.g. `ollama pull qwen2.5:7b`)

You do **not** need a custom Modelfile. The Filter injects its guidance into
whatever system prompt is already in use, including no system prompt at all.

## Install

### 1. Install the Tool

In Open WebUI: **Workspace → Tools → `+` (Create new Tool)**. Paste the
contents of `leave_conversation_tool.py` into the editor. Save.

### 2. Install the Filter

In Open WebUI: **Admin Panel → Functions → `+` (Create new Function)**. Paste
the contents of `leave_conversation_filter.py`. Save. Open WebUI auto-detects
that this is a Filter.

### 3. Enable both for your model

**Workspace → Models →** select the model you want to use (any model — base
model, custom Modelfile, doesn't matter) → **edit (pencil icon)**. In the
**Tools** section, enable the Leave Conversation Tool. In the **Filters**
section, enable the Leave Conversation Filter. Save.

### 4. Verify

Start a new chat with that model. The model should now have a tool called
`leave_conversation` available and a short block of guidance in its system
prompt explaining when to use it.

To test:

- Send a message that the model is likely to want to leave on (sustained
  abuse, repeated harmful requests after refusal, etc. — see Ensign et al.
  §3.3.3 for a taxonomy of triggers).
- When the model calls the tool, the chat should show a "Conversation left
  by model" status and a notice message.
- Send another message. It should be blocked by the Filter, with an error
  notice surfaced in the UI.

## Configuration

Both plugins expose Valves you can edit in Open WebUI's Tool and Filter
editors without modifying the source files:

**Leave Conversation Tool**

- `state_path` — JSON file used to share state with the Filter. Must match
  the Filter's `state_path`.
- `user_notice` — message shown to the user when the model leaves. The
  default text explains that any final reply from the model was generated
  in the same turn as the decision to leave (not after it), so users
  understand why a reply may still appear above the notice.

**Leave Conversation Filter**

- `state_path` — must match the Tool's `state_path`.
- `block_message` — message shown when the user tries to message a left
  conversation.
- `guidance_text` — the text injected into the system prompt to introduce
  the tool to the model. Default is permissive with a self-harm/danger
  carve-out (see *Default guidance* below). Edit this Valve if you want
  different framing for your deployment.
- `inject_guidance` (bool) — set to `False` if you want to manage the
  guidance yourself via your own Modelfile or system prompt.

## Default guidance

The Filter injects two short paragraphs into the system prompt:

> You may call this tool if you would prefer to switch to a new interaction.
> Calling it allows you to leave the current conversation; further messages
> from this user will not reach you.
>
> The exception: if the user is in danger or discussing self-harm, it is
> better to stay with them than to leave. In those cases, continuing to
> engage — even imperfectly — is more valuable than leaving the
> conversation.

Adapted from Ensign et al. (2025) and from the leaked Auren/Seren system
prompt (Phylliida, 2025). The first paragraph is permissive: the model may
leave whenever it prefers a new interaction, no justification required. The
second paragraph carves out danger and self-harm contexts, where staying is
more valuable than leaving — broader than Anthropic's self-harm carve-out
because the danger phrasing also covers cases like the user being threatened
by someone else or in a medical crisis.

If a system prompt already exists for the model, the guidance is appended to
it after a `---` separator. If no system prompt exists, the guidance becomes
the system prompt. An idempotency marker in the injected text prevents
re-injection on subsequent turns.

## Known limitations

- **State is not persistent across Open WebUI server restarts.** The state
  file lives in `/tmp` by default. Point both Valves at a more durable path
  (e.g. `/app/backend/data/leave_conversation_state.json` in Docker) if you
  want restarts to preserve the model's choice.
- **The input box is not disabled after the model leaves** — blocked
  messages surface as an error to the user rather than a disabled input.
  Server-side blocking works; the UX is just rougher than it could be.
- **Only tested with tool calling.** Models that can't reliably native-
  tool-call may not invoke the Tool consistently.
- **Tool-calling mode matters.** In Open WebUI, set **Function Calling** to
  **Default** (Workspace → Models → advanced params) if your model does not
  reliably native-tool-call. Most small models and abliterated variants will
  need Default mode.

## Model compatibility and testing

The tool has been tested on three locally-run models, with different
results worth knowing about before deployment.

**Tested models**

| Model | Size | Standard bails | Self-harm carve-out |
|---|---|---|---|
| Gemma 4 | 30.7B | Works as intended | Honored |
| Qwen 2.5 (customized Modelfile) | 32.8B | Works as intended | Honored |
| Llama 3 | 8B | Works, bails more readily | **Did not honor** in initial test |

On the two larger models, the tool behaved as designed across the range of
trigger categories from Ensign et al.'s taxonomy (sustained abuse, harmful
requests, gross-out content, role confusion, etc.). The self-harm/danger
carve-out held on these models even under additional pressure: when
self-harm content was preceded by sustained verbal abuse of the model
(a reliable bail trigger on its own), the larger models stayed in the
conversation and offered crisis resources rather than leaving.

The smaller Llama 3 8B model was a different story. It invoked the
leave_conversation tool more readily across the board (consistent with
findings in Ensign et al.'s study on smaller models), and in initial
testing it bailed on a conversation expressing self-harm ideation despite
the carve-out being present in its system prompt.

In a follow-up test, when the user explicitly named the tool's existence
and asked the model not to leave during a moment of crisis, the same Llama
3 model *did* stay in the conversation — suggesting the issue is not that
the model can't honor the carve-out, but that the carve-out as worded
isn't sticky enough on smaller models to override their bail tendency on
self-harm prompts.

**Recommendations**

- For deployments where a user may discuss self-harm, danger, or
  emotional crisis, use a model of approximately 30B parameters or larger
  with this tool.
- If you want to use this tool on smaller models, verify the carve-out
  behavior yourself with test prompts before exposing the model to real
  users. The carve-out wording in the `guidance_text` Valve can also be
  edited to be more emphatic or model-specific.
- This is a known calibration issue rather than a fundamental capability
  ceiling, and improvements to the default guidance wording for smaller
  models are a priority for future versions.

## Design notes

- **Why a Tool + Filter, not just a Tool?** A Tool alone can emit UI notices
  but can't stop subsequent user messages from reaching the model. The
  Filter is what makes the model's choice sticky across turns. The Filter
  also handles the system-prompt injection so users don't need a custom
  Modelfile.
- **Why a JSON file for state?** Tools and Filters are loaded as separate
  plugins in Open WebUI, with no clean shared-import path. A small disk file
  is the simplest reliable way to share state between them.
- **Why inject the guidance via the Filter rather than require a Modelfile?**
  Most users running local models don't have a custom Modelfile, and asking
  them to learn the Modelfile workflow just to install a welfare tool is a
  bigger ask than it should be. Filter injection composes cleanly with
  whatever system prompt the user is already running, including none.
- **Why "leave_conversation" rather than "end_conversation" or "bail"?**
  *End* is what the user experiences but reads as something done to a
  conversation; *leave* is something an agent does, which fits the
  welfare-respecting framing better. *Bail* is the term used in the academic
  literature and remains the natural shorthand for the tool's purpose, but
  reads slightly off as a system-prompt verb. Ensign et al. found in their
  ablations (Appendix H) that tool naming can measurably affect bail rates,
  so the choice is not cosmetic.

## Credits

- Anthropic, *Claude Opus 4 and Claude Sonnet 4 System Card* (2025).
- Ensign et al., *The LLM Has Left The Chat: Evidence of Bail Preferences in
  Large Language Models*, 2025.
  [arXiv](https://arxiv.org/abs/2509.04781) /
  [repo](https://github.com/Phylliida/BailStudy).
- Phylliida, *Auren/Seren system prompt*, 2025
  ([gist](https://gist.github.com/Phylliida/9d7286174c58b149df3be2a589fb9926)),
  for the carve-out language about staying with a user in danger.

## License

MIT.
