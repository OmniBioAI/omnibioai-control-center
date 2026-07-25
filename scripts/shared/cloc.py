from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

EXCLUDE_DIRS = (
    "obsolete,staticfiles,node_modules,.venv,env,__pycache__,migrations,"
    "admin,venv,gnn_env,venv_sys,work,input,demo,md"
)

EXCLUDE_EXTS  = "svg,json,txt,csv,lock,min.js,map,pyc"

NOT_MATCH_D   = r"(data|uploads|downloads|cache|results|logs)"

@dataclass
class Totals:
    files: int = 0; blank: int = 0; comment: int = 0; code: int = 0
    def add(self, o: "Totals") -> None:
        self.files += o.files; self.blank += o.blank
        self.comment += o.comment; self.code += o.code

def ensure_cloc() -> None:
    if shutil.which("cloc") is None:
        raise RuntimeError("cloc not found. Install: sudo apt-get install cloc")

def validate_paths(paths: List[Path]) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("⚠ Repo paths not found:")
        for m in missing: print(f"  - {m}")

def _resolve_target_paths(root: Path, targets: List[str]) -> List[Path]:
    norm_map: Dict[str, Path] = {}
    if root.is_dir():
        for e in root.iterdir():
            if e.is_dir():
                norm_map[e.name.lower().replace("-", "_")] = e
    paths: List[Path] = []
    for name in targets:
        exact = root / name
        if exact.is_dir():
            paths.append(exact)
        else:
            nk = name.lower().replace("-", "_")
            resolved = norm_map.get(nk)
            if resolved:
                print(f"  ↳ resolved '{name}' → '{resolved.name}'")
                paths.append(resolved)
            else:
                paths.append(exact)
    return paths

def run_cloc(path: Path) -> Tuple[Totals, Dict[str, Totals]]:
    cmd = ["cloc", str(path),
           "--exclude-dir", EXCLUDE_DIRS,
           "--exclude-ext", EXCLUDE_EXTS,
           "--fullpath", "--not-match-d", NOT_MATCH_D,
           "--force-lang", "Dockerfile,Dockerfile", "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cloc failed for {path}:\n{proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if "SUM" not in data:
        raise RuntimeError(f"Unexpected cloc JSON for {path}.")
    s = data["SUM"]
    overall = Totals(files=int(s.get("nFiles", 0)), blank=int(s.get("blank", 0)),
                     comment=int(s.get("comment", 0)), code=int(s.get("code", 0)))
    per_lang: Dict[str, Totals] = {}
    for k, v in data.items():
        if k in ("header", "SUM"): continue
        if isinstance(v, dict) and "code" in v:
            per_lang[k] = Totals(files=int(v.get("nFiles", 0)),
                                  blank=int(v.get("blank", 0)),
                                  comment=int(v.get("comment", 0)),
                                  code=int(v.get("code", 0)))
    return overall, per_lang
