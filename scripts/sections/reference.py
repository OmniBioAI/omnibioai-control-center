from __future__ import annotations

def reference_section_html(control_center_url: str) -> str:
    """Fetch reference genome data status from control center."""
    import urllib.request, json

    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/reference", timeout=5
        ) as r:
            data = json.loads(r.read())
    except Exception:
        pass

    if not data.get("available"):
        ref_root = data.get("ref_root", "omnibioai-data/reference/")
        return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Reference Data</h2>
  <p style="color:var(--color-text-muted);font-size:13px">
    Reference data directory not found. Expected at:
    <code style="font-family:monospace;color:#a855f7">{ref_root}</code>
  </p>
</div>"""

    organisms = data.get("organisms", [])
    databases = data.get("databases", {})

    ORGANISM_ICONS = {
        "human": "🧬", "mouse": "🐭", "rat": "🐀",
        "zebrafish": "🐟", "drosophila": "🪰", "yeast": "🧫",
        "chimpanzee": "🐒", "macaque": "🐵",
        "celegans": "🪱", "arabidopsis": "🌿", "pig": "🐷", "chicken": "🐔",
    }
    ORGANISM_LABELS = {
        "human": "Human", "mouse": "Mouse", "rat": "Rat",
        "zebrafish": "Zebrafish", "drosophila": "Drosophila", "yeast": "Yeast",
        "chimpanzee": "Chimpanzee", "macaque": "Macaque",
        "celegans": "C. elegans", "arabidopsis": "Arabidopsis",
        "pig": "Pig", "chicken": "Chicken",
    }

    def check(ok: bool) -> str:
        color = "#00e5a0" if ok else "#374151"
        mark = "✓" if ok else "·"
        return f'<span style="color:{color};font-size:14px">{mark}</span>'

    org_rows = ""
    for org in organisms:
        name = org["organism"]
        assembly = org["assembly"]
        icon = ORGANISM_ICONS.get(name, "🧬")
        label = ORGANISM_LABELS.get(name, name.title())
        indexes = org.get("indexes", {})
        variants = org.get("variants", {})

        idx_cells = "".join(
            f'<td style="padding:8px 12px;text-align:center">{check(indexes.get(idx, False))}</td>'
            for idx in ["star", "bwa", "bowtie2", "salmon", "cellranger"]
        )
        var_cells = "".join(
            f'<td style="padding:8px 12px;text-align:center">{check(variants.get(vdb, False))}</td>'
            for vdb in ["clinvar", "dbsnp", "gnomad", "cosmic"]
        )

        org_rows += f"""
        <tr style="border-bottom:1px solid var(--color-border)">
          <td style="padding:8px 16px;font-weight:600;color:var(--color-text)">{icon} {label}</td>
          <td style="padding:8px 12px;font-family:monospace;font-size:11px;color:#a855f7">{assembly}</td>
          {idx_cells}
          {var_cells}
        </tr>"""

    if not org_rows:
        org_rows = '<tr><td colspan="11" style="padding:20px 16px;color:var(--color-text-muted)">No reference organisms found</td></tr>'

    DB_LABELS = {
        "clinvar": "ClinVar", "cosmic": "COSMIC", "dbsnp": "dbSNP",
        "gnomad": "gnomAD", "go": "Gene Ontology", "interpro": "InterPro",
        "pfam": "Pfam", "uniprot": "UniProt"
    }
    db_cards = ""
    for db, present in databases.items():
        color = "#00e5a0" if present else "#6b7280"
        bg = "rgba(0,229,160,0.1)" if present else "rgba(107,114,128,0.1)"
        label = DB_LABELS.get(db, db.upper())
        status = "✓ Available" if present else "Not downloaded"
        db_cards += f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:8px;padding:12px 14px;display:flex;
          align-items:center;justify-content:space-between">
          <span style="font-size:13px;font-weight:600;color:var(--color-text)">{label}</span>
          <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
            background:{bg};color:{color}">{status}</span>
        </div>"""

    if not db_cards:
        db_cards = '<p style="color:var(--color-text-muted);padding:16px">No database info available</p>'

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Reference Data</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    Reference genomes, indexes, and databases available on this machine
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden;margin-bottom:20px">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Reference Genomes &amp; Indexes</span>
    </div>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead>
          <tr style="border-bottom:1px solid var(--color-border);background:rgba(255,255,255,0.02)">
            <th style="padding:8px 16px;text-align:left;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Organism</th>
            <th style="padding:8px 12px;text-align:left;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Assembly</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">STAR</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">BWA</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Bowtie2</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">Salmon</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">CellRanger</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">ClinVar</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">dbSNP</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">gnomAD</th>
            <th style="padding:8px 12px;text-align:center;color:var(--color-text-muted);font-size:10px;font-weight:700;text-transform:uppercase">COSMIC</th>
          </tr>
        </thead>
        <tbody>{org_rows}</tbody>
      </table>
    </div>
    <p style="font-size:11px;color:var(--color-text-muted);margin-top:8px;padding:0 4px">
      * Zebrafish (GRCz11) STAR index requires 141GB RAM —
      exceeds DGX Spark capacity (128GB).
      Salmon and Bowtie2 indexes available.
      STAR index will be added post-launch.
    </p>
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border)">
      <span style="font-weight:700;font-size:13px">Annotation Databases</span>
    </div>
    <div style="padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px">
      {db_cards}
    </div>
  </div>
</div>"""
