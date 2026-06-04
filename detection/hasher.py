import hashlib


# SHA256 is a cryptographic hash function: it maps any input string to a fixed
# 64-character hexadecimal output. The same input ALWAYS produces the same output.
# A single character change produces a completely different hash.
#
# Why SHA256 instead of MD5?
#   MD5 is faster but has known collision vulnerabilities (two different inputs can
#   produce the same hash). For security-sensitive use SHA256 is safer.
#   For our use case (change detection, not security), MD5 would also work fine —
#   we chose SHA256 as best practice.
#
# Why SHA256 instead of a simple str comparison?
#   Comparing two 64-character hashes is O(1) constant time.
#   Comparing two 10,000-character page texts is O(n). Hashing first lets us skip
#   the expensive string comparison for unchanged pages.
def compute_hash(text: str) -> str:
    # .encode("utf-8") converts the string to bytes — hashlib operates on bytes, not strings.
    # UTF-8 is the standard encoding; it handles all Unicode characters (Hindi, emojis, etc.).
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Returns True if the new content differs from what was previously stored.
# Called before every expensive diff computation — if this returns False, we skip everything.
def content_changed(new_text: str, old_hash: str) -> bool:
    return compute_hash(new_text) != old_hash
