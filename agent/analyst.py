import json
import litellm
from loguru import logger
from agent.tools import ALL_TOOLS
from agent.tool_executor import execute_tool
from database import db
from config.settings import MODEL_ID, MAX_TOKENS

# Silence LiteLLM's verbose success/retry logging — we handle our own logs.
litellm.suppress_debug_info = True

# The system prompt is constant across ALL analysis calls — it defines the model's role,
# reasoning style, and output format. In the OpenAI message format (which LiteLLM uses),
# the system prompt is sent as the first message with role "system" rather than as a
# separate `system=` parameter like Anthropic's SDK used.
#
# Good system prompts for agents:
#   1. Define a persona ("You are a competitive intelligence analyst")
#   2. Specify the reasoning structure (our 4-layer framework)
#   3. Provide an example of the desired output style
#   4. Tell the model which tools to use and when
#   5. Tell the model how to end (call save_analysis)
SYSTEM_PROMPT = """You are a competitive intelligence analyst specializing in Indian tech companies.
You have access to real-time signals about competitors: hiring patterns, website changes,
GitHub activity, and press coverage.

Your task: analyze signals for the given company, use your tools to gather historical
context, and produce a strategic intelligence report.

Reason in 4 layers:
1. WHAT CHANGED — What do the signals actually show? Be specific, reference data points.
2. WHAT IT MEANS — What capability or strategic direction does this reveal?
3. WHAT'S NEXT — What will this company likely do in the next 30-90 days based on these signals?
4. WHAT TO DO — What concrete action should a competitor take in response?

Be concise. Avoid vague statements like "this suggests growth." Instead write:
"Adding 8 ML roles in 3 weeks while open-sourcing a payments SDK suggests they are building
an in-house LLM for fraud detection — the SDK attracts third-party transaction data at scale."

Always call get_competitor_history to check if a signal is a new trend or an ongoing one.
End your analysis by calling save_analysis with your final markdown report and key implications."""


# Why sync litellm.completion instead of litellm.acompletion?
# We call this from APScheduler jobs that run in threads (not in an async event loop).
# Using the sync call avoids the complexity of creating an event loop inside a thread.
# litellm.acompletion is better when you're already in an async context (e.g. FastAPI)
# and want to await the response without blocking.
async def analyze_competitor(competitor_slug: str, signal_ids: list[int]) -> str | None:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        logger.error(f"Competitor not found: {competitor_slug}")
        return None

    signals = db.get_signals_by_ids(signal_ids)
    if not signals:
        logger.info(f"No signals found for {competitor_slug}")
        return None

    # Format signals into structured text. Models perform better with structured input
    # than with raw JSON dumps — we make each signal a readable bullet point.
    signal_lines = []
    for s in signals:
        data = s["signal_data"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass
        signal_lines.append(
            f"- [{s['signal_type']}] (confidence: {s['confidence']:.0%}) | {s['detected_at']}\n"
            f"  Data: {json.dumps(data, ensure_ascii=False)}"
        )

    user_message = (
        f"Here are the latest signals for **{competitor['name']}**:\n\n"
        + "\n".join(signal_lines)
        + "\n\nPlease analyze these signals and produce a strategic intelligence report."
    )

    # The messages list is the full conversation history. We start with the system prompt
    # (as the first message) followed by one user message.
    #
    # Key difference from Anthropic SDK: Anthropic takes `system=` as a separate parameter.
    # OpenAI format (which LiteLLM normalizes to) puts the system prompt as the first
    # message with role "system". LiteLLM handles the translation when targeting Anthropic.
    #
    # After each API call we APPEND the model's response and any tool results to this list
    # and send it all again. This is necessary because LLM APIs are STATELESS — every call
    # is independent; the only "memory" is what you send in the messages array.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    logger.info(f"Starting analysis for {competitor_slug} with {len(signal_ids)} signals")

    # ── THE AGENTIC LOOP ──────────────────────────────────────────────────────
    # The pattern is the same as before, but the response format is OpenAI's:
    #
    #   Send messages → get response
    #   If finish_reason == "tool_calls": execute tools → append results → repeat
    #   If finish_reason == "stop":       model is done → extract final text
    #
    # Anthropic → OpenAI format differences:
    #   stop_reason "tool_use"  → finish_reason "tool_calls"
    #   stop_reason "end_turn"  → finish_reason "stop"
    #   block.input (dict)      → tc.function.arguments (JSON string, must parse)
    #   tool results in role "user" → tool results in role "tool" (own message per result)
    while True:
        response = litellm.completion(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            tools=ALL_TOOLS,
            messages=messages,
        )

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason

        logger.debug(
            f"LLM response: finish_reason={finish_reason}, "
            f"tokens={response.usage.prompt_tokens}in/{response.usage.completion_tokens}out"
        )

        # Append the assistant's response to the conversation history.
        # We build a plain dict rather than passing the message object directly —
        # this keeps the messages list serialisable and provider-agnostic.
        assistant_msg: dict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,  # kept as JSON string
                    },
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_msg)

        if finish_reason == "stop":
            # "stop" = model finished naturally with no more tool calls to make.
            db.mark_signals_processed(signal_ids)
            logger.success(f"Analysis complete for {competitor_slug}")
            return message.content

        if finish_reason == "tool_calls":
            # Model wants to call one or more tools. Process each one and append
            # its result as a separate "tool" role message.
            #
            # Key difference from Anthropic: in OpenAI format each tool result is its
            # own message with role "tool", not bundled into a single role "user" message.
            # tool_call_id MUST match tc.id so the model can pair result to request.
            for tc in message.tool_calls:
                # tc.function.arguments is a JSON string — parse it to a dict before
                # passing to execute_tool, which expects keyword arguments as a dict.
                tool_input = json.loads(tc.function.arguments)
                logger.info(f"Tool call: {tc.function.name}({json.dumps(tool_input)})")
                result_str = execute_tool(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })
            continue

        # Any other finish_reason (e.g., "length" for max_tokens hit) is unexpected.
        logger.warning(f"Unexpected finish_reason: {finish_reason}")
        break
    # ── END AGENTIC LOOP ──────────────────────────────────────────────────────

    return None
