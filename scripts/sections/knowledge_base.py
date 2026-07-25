from __future__ import annotations

def knowledge_base_section_html(control_center_url: str) -> str:
    """Fetch AI knowledge base stats from control center."""
    import urllib.request, json

    data: dict = {}
    try:
        with urllib.request.urlopen(
            f"{control_center_url.rstrip('/')}/knowledge-base", timeout=250
        ) as r:
            data = json.loads(r.read())
    except Exception:
        pass

    if not data:
        return """
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">AI Knowledge Base</h2>
  <p style="color:var(--color-text-muted);font-size:13px">
    Could not reach control center for knowledge base stats.
  </p>
</div>"""

    abstracts = data.get("abstracts", {})
    faiss = data.get("faiss_index", {})
    rag_status = data.get("rag_status", "unknown")

    total_abstracts = abstracts.get("total", 0)
    domains_with_abstracts = abstracts.get("domains_with_abstracts", 0)
    domains_indexed = faiss.get("domains_indexed", 0)
    index_size_gb = faiss.get("size_gb", 0)
    domain_list = faiss.get("domain_list", [])

    rag_color = "#00e5a0" if rag_status == "running" else "#ef4444"
    rag_bg = "rgba(0,229,160,0.15)" if rag_status == "running" else "rgba(239,68,68,0.15)"

    def stat_card(value, label, color="#00e5a0"):
        return f"""
        <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
          border-radius:10px;padding:20px 24px;text-align:center">
          <div style="font-size:32px;font-weight:800;color:{color};
            font-family:var(--font-mono);margin-bottom:4px">{value}</div>
          <div style="font-size:11px;font-weight:600;color:var(--color-text-muted);
            text-transform:uppercase;letter-spacing:0.06em">{label}</div>
        </div>"""

    if total_abstracts >= 1_000_000:
        abs_display = f"{total_abstracts/1_000_000:.1f}M"
    elif total_abstracts >= 1_000:
        abs_display = f"{total_abstracts/1_000:.0f}K"
    else:
        abs_display = str(total_abstracts)

    domain_tags = ""
    for domain in domain_list:
        domain_tags += f"""
        <span style="display:inline-block;font-size:10px;padding:3px 8px;
          border-radius:99px;background:rgba(168,85,247,0.15);
          color:#a855f7;border:1px solid rgba(168,85,247,0.3);
          margin:2px;font-family:var(--font-mono)">{domain}</span>"""

    return f"""
<div class="tab-section">
  <h2 style="font-size:18px;font-weight:700;margin-bottom:4px">AI Knowledge Base</h2>
  <p style="color:var(--color-text-muted);font-size:13px;margin-bottom:20px">
    PubMed literature indexed locally · FAISS vector search · RAG pipeline
  </p>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;padding:12px 16px;margin-bottom:16px;
    display:flex;align-items:center;justify-content:space-between">
    <span style="font-weight:700;font-size:13px">RAG Service</span>
    <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;
      background:{rag_bg};color:{rag_color}">{rag_status.upper()}</span>
  </div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px">
    {stat_card(abs_display, "PubMed Abstracts")}
    {stat_card(domains_with_abstracts, "Domains Ingested", "#a855f7")}
    {stat_card(domains_indexed, "FAISS Indexes", "#f59e0b")}
    {stat_card(f"{index_size_gb} GB", "Index Size", "#06b6d4")}
  </div>

  <div style="background:var(--color-bg-surface);border:1px solid var(--color-border);
    border-radius:10px;overflow:hidden">
    <div style="padding:12px 16px;border-bottom:1px solid var(--color-border);
      display:flex;align-items:center;justify-content:space-between">
      <span style="font-weight:700;font-size:13px">Indexed Domains (showing first 20)</span>
      <span style="font-size:11px;color:var(--color-text-muted)">{domains_indexed} total</span>
    </div>
    <div style="padding:14px 16px">
      {domain_tags if domain_tags else
        '<p style="color:var(--color-text-muted);font-size:12px">No domains indexed yet</p>'}
    </div>
  </div>
</div>"""
