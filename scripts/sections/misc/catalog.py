from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None  # tools-count degrades gracefully if pyyaml missing

from shared.cloc import EXCLUDE_DIRS
from shared.helpers import fmt_int

CATALOG_BACKEND_COLORS = {
    "slurm": "#3C3489", "http": "#0F6E56", "aws_batch": "#854F0B",
    "gcp_batch": "#185FA5", "azure_batch": "#A32D2D", "kubernetes": "#7F77DD",
    "unknown": "#444441",
}

WORKFLOW_EXTS = {
    ".nf": "Nextflow", ".wdl": "WDL", ".cwl": "CWL", ".smk": "Snakemake",
}

WORKFLOW_SPECIAL_NAMES = {
    "Snakefile": "Snakemake", "main.nf": "Nextflow",
}

def _count_plugins(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """Counts plugin directories under omnibioai/plugins/ that contain a plugin.json."""
    plugins_dir = ecosystem_root / "omnibioai" / "plugins"
    if not plugins_dir.is_dir():
        return 0, {}
    by_category: Dict[str, int] = {}
    count = 0
    for entry in plugins_dir.iterdir():
        if not entry.is_dir():
            continue
        pj = entry / "plugin.json"
        if not pj.exists():
            continue
        count += 1
        try:
            meta = json.loads(pj.read_text(encoding="utf-8"))
            cat = str(meta.get("category", "uncategorized"))
        except Exception:
            cat = "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
    return count, by_category

def _infer_tool_backend(tool: Dict[str, Any]) -> str:
    for key, backend in (
        ("slurm", "slurm"), ("http", "http"),
        ("aws_batch", "aws_batch"), ("aws", "aws_batch"),
        ("gcp_batch", "gcp_batch"), ("gcp", "gcp_batch"),
        ("azure_batch", "azure_batch"), ("azure", "azure_batch"),
        ("kubernetes", "kubernetes"), ("k8s", "kubernetes"),
    ):
        if key in tool:
            return backend
    return "unknown"

def _count_tes_tools(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """
    Counts tools from the live TES API if reachable (ground truth), else falls
    back to reading omnibioai-tes/configs/tools/*.yaml + x86_64/*.yaml directly
    (NOT tools.example.yaml, which is generated and can drift).

    Each category YAML file's root is a plain list of tool dicts (verified
    against configs/tools/01_qc_preprocessing.yaml etc.), not {"tools": [...]}.
    """
    try:
        req = urllib.request.Request(
            "http://tes:8081/api/tools",
            headers={"User-Agent": "omnibioai-report/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tools = json.loads(resp.read().decode("utf-8"))
        by_backend: Dict[str, int] = {}
        for t in tools:
            tags = set(t.get("tags") or [])
            backend = next(
                (b for b in ("slurm", "http", "aws_batch", "gcp_batch",
                              "azure_batch", "kubernetes", "k8s") if b in tags),
                "unknown")
            by_backend[backend] = by_backend.get(backend, 0) + 1
        return len(tools), by_backend
    except Exception:
        pass  # fall through to static file counting

    if yaml is None:
        return 0, {}
    tools_dir = ecosystem_root / "omnibioai-tes" / "configs" / "tools"
    if not tools_dir.is_dir():
        return 0, {}
    yaml_files = list(tools_dir.glob("*.yaml")) + list(tools_dir.glob("x86_64/*.yaml"))
    total = 0
    by_backend: Dict[str, int] = {}
    for yf in yaml_files:
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or []
        except Exception:
            continue
        tools = data.get("tools", []) if isinstance(data, dict) else data
        for t in (tools or []):
            total += 1
            backend = _infer_tool_backend(t)
            by_backend[backend] = by_backend.get(backend, 0) + 1
    return total, by_backend

def _count_workflow_bundles(ecosystem_root: Path) -> Tuple[int, Dict[str, int]]:
    """
    Counts workflow bundles under omnibioai-workflow-bundles/ by locating
    workflow definition files (Nextflow .nf, WDL .wdl, CWL .cwl, Snakemake
    Snakefile/.smk) and deduplicating by parent directory -- one bundle
    directory may contain a main workflow file plus supporting files, so
    counting files directly would overcount.
    """
    bundles_dir = ecosystem_root / "omnibioai-workflow-bundles"
    if not bundles_dir.is_dir():
        return 0, {}
    exclude_names = set(EXCLUDE_DIRS.split(","))
    bundle_dirs: Dict[Path, str] = {}
    for ext, label in WORKFLOW_EXTS.items():
        for f in bundles_dir.rglob(f"*{ext}"):
            if any(part in exclude_names or part.startswith(".") for part in f.parts):
                continue
            bundle_dirs.setdefault(f.parent, label)
    for name, label in WORKFLOW_SPECIAL_NAMES.items():
        for f in bundles_dir.rglob(name):
            if any(part in exclude_names or part.startswith(".") for part in f.parts):
                continue
            bundle_dirs.setdefault(f.parent, label)
    by_type: Dict[str, int] = {}
    for _, label in bundle_dirs.items():
        by_type[label] = by_type.get(label, 0) + 1
    return len(bundle_dirs), by_type

def catalog_section_html(ecosystem_root: Path) -> str:
    plugin_count, plugin_cats = _count_plugins(ecosystem_root)
    tool_count, tool_backends = _count_tes_tools(ecosystem_root)
    workflow_count, workflow_types = _count_workflow_bundles(ecosystem_root)

    def _breakdown_rows(d: Dict[str, int], color_map: Optional[Dict[str, str]] = None) -> str:
        if not d:
            return '<div style="font-size:12px;color:var(--color-text-muted);padding:8px">no breakdown available</div>'
        total = sum(d.values()) or 1
        rows = ""
        for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True):
            color = (color_map or {}).get(k, "#0094ff")
            pct = round(100 * v / total, 1)
            rows += f"""
            <div class="bar-row">
              <span class="bar-label" style="width:120px">{k}</span>
              <div class="bar-track" style="height:14px">
                <div class="bar-fill" style="width:{pct}%;background:{color}22"></div>
                <span class="bar-val" style="color:{color}">{fmt_int(v)}</span>
              </div>
            </div>"""
        return rows

    return f"""
<div class="tab-section">
<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">plugins</div><div class="kpi-val">{fmt_int(plugin_count)}</div><div class="kpi-sub">omnibioai/plugins</div></div>
  <div class="kpi"><div class="kpi-label">tools</div><div class="kpi-val">{fmt_int(tool_count)}</div><div class="kpi-sub">omnibioai-tes</div></div>
  <div class="kpi"><div class="kpi-label">workflow bundles</div><div class="kpi-val">{fmt_int(workflow_count)}</div><div class="kpi-sub">omnibioai-workflow-bundles</div></div>
  <div class="kpi"><div class="kpi-label">total catalog</div><div class="kpi-val">{fmt_int(plugin_count + tool_count + workflow_count)}</div><div class="kpi-sub">plugins + tools + workflows</div></div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
  <div class="section">
    <div class="sec-title">plugins by category</div>
    <div class="sec-sub">omnibioai/plugins/*/plugin.json</div>
    {_breakdown_rows(plugin_cats)}
  </div>
  <div class="section">
    <div class="sec-title">tools by backend</div>
    <div class="sec-sub">live TES API if reachable, else configs/tools/*.yaml</div>
    {_breakdown_rows(tool_backends, CATALOG_BACKEND_COLORS)}
  </div>
  <div class="section">
    <div class="sec-title">workflow bundles by type</div>
    <div class="sec-sub">Nextflow / WDL / CWL / Snakemake</div>
    {_breakdown_rows(workflow_types)}
  </div>
</div>

<div style="font-size:11px;color:var(--color-text-muted);margin-top:12px;padding:8px 0;border-top:0.5px solid var(--color-border)">
  Tool count prefers the live TES API (ground truth) when reachable at http://tes:8081;
  falls back to static YAML file counting otherwise. Plugin/workflow counts are
  filesystem-based and reflect what's on disk at report-generation time.
</div>
</div>
"""
