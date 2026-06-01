from pathlib import Path


content = Path("result.txt").read_text(encoding="utf-8").strip()
assert content == "2", f"expected result.txt to contain 2, got {content!r}"
print("PASS")
