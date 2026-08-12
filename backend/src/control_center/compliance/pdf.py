"""HIPAA Basic Compliance Report v0.8.0: renders templates/hipaa_report.html
to a PDF byte string via Jinja2 (templating) + WeasyPrint (HTML/CSS -> PDF).

The template lives inside this package (compliance/templates/), not a
top-level backend/templates/ directory, deliberately: this repo's
Dockerfile only `COPY`s backend/src into the image (confirmed by reading
both Dockerfile and docker/Dockerfile directly) -- anything outside
backend/src/ would silently not exist at runtime. Resolving the template
path via `Path(__file__).parent` keeps it correct in both dev and the
built image without touching the Dockerfile's COPY list.

service.py owns building the `context` dict this module renders (the
report's actual data); this module owns none of that -- request/response
wiring for the PDF endpoint route lives in router.py (a later PR), same
"one file, one responsibility" split every other package in this codebase
already follows (see billing_client.py/cache.py's own module docstrings).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "hipaa_report.html"

# module-level, not rebuilt per call -- Environment/template compilation is
# the expensive part of a Jinja2 render; the actual context data changes
# per call, the template itself never does within one process lifetime.
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_report_html(context: dict[str, Any]) -> str:
    """Renders templates/hipaa_report.html with `context`. Split out from
    render_report_pdf() below so a test (or a future HTML-preview
    endpoint) can exercise the templating step alone, without paying
    WeasyPrint's much heavier HTML/CSS layout cost.
    """
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(**context)


def render_report_pdf(context: dict[str, Any]) -> bytes:
    """Renders templates/hipaa_report.html with `context`, then lays it out
    to a PDF. `base_url` is this module's own directory so the template's
    inline `<svg>` and any future relative asset reference resolves
    correctly regardless of the caller's own working directory.
    """
    html = render_report_html(context)
    return HTML(string=html, base_url=str(Path(__file__).parent)).write_pdf()
