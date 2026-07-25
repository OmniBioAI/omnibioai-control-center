from __future__ import annotations

import json
from pathlib import Path

def fmt_int(n: int) -> str: return f"{n:,}"

def safe_div(a: float, b: float) -> float: return (a / b) if b else 0.0

def _jsl(items): return "[" + ",".join(json.dumps(s) for s in items) + "]"

def _jsn(items): return "[" + ",".join(str(round(v, 2)) for v in items) + "]"

def _read_text_if_exists(path: Path) -> str:
    try: return path.read_text(encoding="utf-8")
    except Exception: return ""
