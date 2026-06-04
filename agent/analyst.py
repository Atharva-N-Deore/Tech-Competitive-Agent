import json
import anthropic
from loguru import logger
from agent.tools import ALL_TOOLS
from agent.tool_executor import execute_tool
from database import db
from config.settings import ANTHROPIC_API_KEY, MODEL_ID, MAX_TOKENS

# The system prompt is constant across ALL analysis calls — it defines Claude's role,
# reasoning style, and output format. It is sent with every API call but does not
# appear in the `messages` list (it has its own dedicated `system` parameter).
#
# Good system prompts for agents:
#   1. Define a persona ("You are a competitive intelligence analyst")
#   2. Specify the reasoning structure (our 4-layer framework)
#   3. Provide an example of the desired output style
#   4. Tell Claude which tools to use and when
#   5. Tell Claude how to end (call save_analysis)
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


# Why sync anthropic.Anthropic instead of anthropic.AsyncAnthropic?
# We call this from APScheduler jobs that run in threads (not in an async event loop).
# Using the sync client avoids the complexity of creating an event loop inside a thread.
# The async client (AsyncAnthropic) is better when you're already in an async context
# (e.g., a FastAPI endpoint) and want to await the response without blocking.
async def analyze_competitor(competitor_slug: str, signal_ids: list[int]) -> str | None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        logger.error(f"Competitor not found: {competitor_slug}")
        return None

    signals = db.get_signals_by_ids(signal_ids)
    if not signals:
        logger.info(f"No signals found for {competitor_slug}")
        return None

    # Format signals into structured text. Claude performs better with structured input
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

    # The messages list is the full conversation history. We start with one user message.
    # After each API call, we APPEND Claude's response to this list and send it all again.
    # This is necessary because the Claude API is STATELESS — it has no memory between calls.
    # Every call is independent; the only "memory" is what you send in the messages array.
    messages = [{"role": "user", "content": user_message}]

    logger.info(f"Starting analysis for {competitor_slug} with {len(signal_ids)} signals")

    # ── THE AGENTIC LOOP ──────────────────────────────────────────────────────
    # This is the core pattern of any Claude-powered agent:
    #
    #   Send messages → get response
    #   If stop_reason == "tool_use": execute tools → append results → repeat
    #   If stop_reason == "end_turn": Claude is done → extract final text
    #
    # The loop can cycle multiple times before Claude finishes. Each iteration
    # adds more context (tool results) to the conversation.
    while True:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=ALL_TOOLS,    # Claude can see these tool definitions
            messages=messages,  # full conversation history
        )

        logger.debug(
            f"Claude response: stop_reason={response.stop_reason}, "
            f"blocks={[b.type for b in response.content]}, "
            f"tokens={response.usage.input_tokens}in/{response.usage.output_tokens}out"
        )

        # Append Claude's response to the conversation history.
        # response.content is a list of content blocks (TextBlock, ToolUseBlock, etc.).
        # We must append it exactly as-is — the SDK accepts this format directly.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # "end_turn" = Claude finished naturally and has no more tool calls to make.
            # The final response may contain multiple blocks — find the TextBlock.
            # hasattr(block, "text") is used instead of block.type == "text" because
            # the SDK might return different block types in different versions.
            final_text = None
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            db.mark_signals_processed(signal_ids)
            logger.success(f"Analysis complete for {competitor_slug}")
            return final_text

        if response.stop_reason == "tool_use":
            # Claude wants to call one or more tools. A single response can request
            # multiple tool calls — process all of them.
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Tool call: {block.name}({json.dumps(block.input)})")
                    result_str = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        # tool_use_id MUST match block.id — Claude uses this to pair
                        # each tool result with the corresponding tool call it made.
                        # Sending the wrong ID causes an API error.
                        "tool_use_id": block.id,
                        "content": result_str,  # must be a string, not a dict
                    })
            # Tool results are sent back as a "user" role message — that's the API convention.
            # Then we loop: Claude receives its tool results and continues reasoning.
            messages.append({"role": "user", "content": tool_results})
            continue

        # Any other stop_reason (e.g., "max_tokens") is unexpected — log and exit.
        logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
        break
    # ── END AGENTIC LOOP ──────────────────────────────────────────────────────

    return None
