import difflib


# Produces a "unified diff" — the same format used by `git diff`.
# Lines starting with "+" are additions, "-" are removals, " " are unchanged context.
# Example output:
#   --- previous
#   +++ current
#   @@ -12,7 +12,8 @@
#    Senior Backend Engineer
#   -Senior ML Engineer
#   +Senior ML Engineer (GenAI)
#   +Staff ML Engineer
#
# Why difflib.unified_diff over other options?
#   - difflib is Python's standard library — no installation needed.
#   - The unified diff format is human-readable and well-understood.
#   - Alternative: `deepdiff` library — better for structured data (dicts, lists),
#     but our snapshots are plain text so unified_diff is the right tool.
#   - Alternative: difflib.ndiff() — shows every line even if unchanged; too verbose.
def generate_diff(old_text: str, new_text: str, context_lines: int = 3) -> str:
    # splitlines(keepends=True) splits on newlines while PRESERVING the \n character.
    # This is required by unified_diff — without keepends=True the output is malformed.
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_iter = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="previous",
        tofile="current",
        n=context_lines,    # how many unchanged lines to show around each changed block
    )
    # unified_diff returns a generator (lazy) — join it into a single string immediately.
    return "".join(diff_iter)


# Returns a float from 0.0 (completely different) to 1.0 (identical).
# Uses the Ratcliff/Obershelp algorithm (longest common subsequence based).
# We use this as a noise filter: pages that are 98%+ similar are skipped —
# tiny changes like a date update or ad rotation don't reach signal extraction.
#
# Alternative: Levenshtein distance — counts minimum character edits. More precise
# but O(n*m) time complexity, which is slow on large pages. SequenceMatcher is faster
# for long strings because it finds matching blocks rather than character edits.
def compute_similarity(old_text: str, new_text: str) -> float:
    # None as the first argument means "use default junk filter" (ignore whitespace-only lines).
    return difflib.SequenceMatcher(None, old_text, new_text).ratio()
