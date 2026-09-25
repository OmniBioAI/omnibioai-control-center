import type { CSSProperties, ReactNode } from 'react'
import { Card } from '../components/ui'
import {
  Badge, ExtLink, Loading, Section, Unavailable, useLoad,
} from '../components/publicShowcase'
import { fetchShowcase, type Showcase } from '../publicOverview'

/**
 * Public Evidence tab (control.omnibioai.org): the material that lets a
 * visitor check the platform's claims -- benchmarks, example analyses,
 * tool versions, CI, test evidence, security controls, releases,
 * publications and known limitations. Content comes from GET /showcase:
 * a reviewed, schema-validated file plus two live sources (GitHub releases,
 * the promoted regression certification). Sections without content are
 * not rendered at all -- no placeholder numbers, and no wall of "coming
 * soon" cards while the content is being prepared.
 */

const TH: CSSProperties = { padding: '10px 14px', textAlign: 'left', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)' }
const TD: CSSProperties = { padding: '8px 14px', fontSize: 13, color: 'var(--text2)', borderTop: '1px solid var(--border)', verticalAlign: 'top' }

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <Card padding={0} style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>{head.map(h => <th key={h} style={TH}>{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </Card>
  )
}

const CONTROL_STATUS: Record<string, { label: string; ok: boolean }> = {
  implemented: { label: 'Implemented', ok: true },
  partial: { label: 'Partial', ok: false },
  planned: { label: 'Planned', ok: false },
}

function Scientific({ s }: { s: Showcase }) {
  return (
    <>
      {s.benchmarks.length > 0 && (
        <Section title="Benchmarks" description="Pipeline results against published reference datasets.">
            <Table head={['Pipeline', 'Dataset', 'Results', 'Date']}>
              {s.benchmarks.map(b => (
                <tr key={`${b.pipeline}/${b.dataset}/${b.date}`}>
                  <td style={TD}>{b.url ? <ExtLink href={b.url}>{b.pipeline}</ExtLink> : b.pipeline}</td>
                  <td style={TD}>{b.dataset}</td>
                  <td style={{ ...TD, fontFamily: 'var(--mono)' }}>
                    {Object.entries(b.metrics).map(([k, v]) => `${k} ${v}`).join(' · ')}
                  </td>
                  <td style={TD}>{b.date}</td>
                </tr>
              ))}
            </Table>
        </Section>
      )}

      {s.example_runs.length > 0 && (
        <Section title="Example analyses" description="Real runs on public data, with inputs and reports you can inspect.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
              {s.example_runs.map(r => (
                <Card key={r.title}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{r.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', margin: '4px 0 8px', fontFamily: 'var(--mono)' }}>{r.dataset}</div>
                  <div style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 }}>{r.description}</div>
                  <div style={{ display: 'flex', gap: 14, marginTop: 10, fontSize: 13 }}>
                    {r.report_url && <ExtLink href={r.report_url}>Report ↗</ExtLink>}
                    {r.inputs_url && <ExtLink href={r.inputs_url}>Inputs ↗</ExtLink>}
                  </div>
                </Card>
              ))}
            </div>
        </Section>
      )}

      {s.tool_versions.length > 0 && (
        <Section title="Tool and database versions" description="Exact versions used by the platform's pipelines.">
            <Table head={['Tool or database', 'Version', 'Category']}>
              {s.tool_versions.map(t => (
                <tr key={`${t.name}/${t.version}`}>
                  <td style={TD}>{t.name}</td>
                  <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{t.version}</td>
                  <td style={TD}>{t.category ?? ''}</td>
                </tr>
              ))}
            </Table>
        </Section>
      )}
    </>
  )
}

function Engineering({ s }: { s: Showcase }) {
  const reg = s.regression
  return (
    <>
      {s.ci_repos.length > 0 && (
        <Section title="Continuous integration" description="Live build status, straight from GitHub Actions.">
            <Card style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
              {s.ci_repos.map(c => (
                <a key={c.repo} href={`https://github.com/${c.repo}/actions/workflows/${c.workflow}`} target="_blank" rel="noreferrer"
                  style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'var(--text2)', fontSize: 13 }}>
                  <span>{c.label ?? c.repo}</span>
                  <img src={`https://github.com/${c.repo}/actions/workflows/${c.workflow}/badge.svg`} alt={`${c.label ?? c.repo} CI status`} height={20} />
                </a>
              ))}
            </Card>
        </Section>
      )}

      {reg && (
        <Section title="End-to-end certification" description="The latest promoted run of the cross-service regression suite.">
            <Card>
              <div style={{ fontSize: 13, color: 'var(--text2)' }}>
                Generated {reg.generated_at ? new Date(reg.generated_at).toLocaleDateString() : 'on an unknown date'}
                {reg.freshness && <span style={{ color: 'var(--muted)' }}> · {reg.freshness.toLowerCase()}</span>}
              </div>
              <div style={{ marginTop: 10 }}>
                {Object.entries(reg.phases).map(([key, p]) => (
                  <Badge key={key} ok={p.certification_status === 'certified'}>
                    {key.toUpperCase()}: {p.certification_status.replace(/_/g, ' ')}
                  </Badge>
                ))}
              </div>
              <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 6 }}>
                {reg.capabilities_total} capabilities tracked:{' '}
                {Object.entries(reg.capabilities_by_certification).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ')}
              </div>
            </Card>
        </Section>
      )}

      {s.test_evidence.length > 0 && (
        <Section title="Test runs" description="Dated results with the full outcome breakdown, not a single pass count.">
            <Table head={['Suite', 'Date', 'Passed', 'Failed', 'Skipped', 'Blocked']}>
              {s.test_evidence.map(t => (
                <tr key={`${t.suite}/${t.date}`}>
                  <td style={TD}>{t.url ? <ExtLink href={t.url}>{t.suite}</ExtLink> : t.suite}</td>
                  <td style={TD}>{t.date}</td>
                  <td style={{ ...TD, color: 'var(--green)' }}>{t.passed}</td>
                  <td style={{ ...TD, color: t.failed ? 'var(--red)' : 'var(--text2)' }}>{t.failed}</td>
                  <td style={TD}>{t.skipped}</td>
                  <td style={TD}>{t.blocked}</td>
                </tr>
              ))}
            </Table>
        </Section>
      )}

      {s.repo_coverage.length > 0 && (
        <Section title="Test coverage by repository" description="Measured per repository and dated; not averaged into one platform-wide figure.">
            <Table head={['Repository', 'Coverage', 'Measured']}>
              {s.repo_coverage.map(c => (
                <tr key={c.repo}>
                  <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{c.repo}</td>
                  <td style={TD}>{c.coverage_pct}%</td>
                  <td style={TD}>{c.date}</td>
                </tr>
              ))}
            </Table>
        </Section>
      )}
    </>
  )
}

function Trust({ s }: { s: Showcase }) {
  return (
    <>
      {s.security_controls.length > 0 && (
        <Section title="Security controls" description="What is implemented today, and what is still partial.">
            <Card padding={0}>
              {s.security_controls.map((c, n) => {
                const st = CONTROL_STATUS[c.status]
                return (
                  <div key={c.area} style={{ padding: '10px 14px', borderTop: n ? '1px solid var(--border)' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{c.area}</span>
                      <Badge ok={st.ok}>{st.label}</Badge>
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 }}>{c.summary}</div>
                  </div>
                )
              })}
            </Card>
        </Section>
      )}

      {s.data_handling.length > 0 && (
        <Section title="Data handling">
            <Card>
              <ul style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {s.data_handling.map(d => <li key={d} style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 }}>{d}</li>)}
              </ul>
            </Card>
        </Section>
      )}

      {s.limitations.length > 0 && (
        <Section title="Known limitations" description="What does not work yet, stated plainly.">
            <Card padding={0}>
              {s.limitations.map((l, n) => (
                <div key={l.title} style={{ padding: '10px 14px', borderTop: n ? '1px solid var(--border)' : 'none' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
                    {l.url ? <ExtLink href={l.url}>{l.title} ↗</ExtLink> : l.title}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 }}>{l.detail}</div>
                </div>
              ))}
            </Card>
        </Section>
      )}
    </>
  )
}

function History({ s }: { s: Showcase }) {
  return (
    <>
      {s.releases.length > 0 && (
        <Section title="Releases">
            <Table head={['Version', 'Released']}>
              {s.releases.map(r => (
                <tr key={r.version}>
                  <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{r.url ? <ExtLink href={r.url}>{r.version}</ExtLink> : r.version}</td>
                  <td style={TD}>{r.date ?? ''}</td>
                </tr>
              ))}
            </Table>
        </Section>
      )}

      {s.publications.length > 0 && (
        <Section title="Publications">
            <Card padding={0}>
              {s.publications.map((p, n) => (
                <div key={p.title} style={{ display: 'flex', gap: 14, padding: '10px 14px', borderTop: n ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--accent)', paddingTop: 2 }}>{p.year}</span>
                  <div>
                    <div style={{ fontSize: 13, color: 'var(--text)' }}>{p.url ? <ExtLink href={p.url}>{p.title}</ExtLink> : p.title}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>{p.venue}</div>
                  </div>
                </div>
              ))}
            </Card>
        </Section>
      )}
    </>
  )
}

function hasContent(s: Showcase): boolean {
  return [
    s.benchmarks, s.example_runs, s.tool_versions, s.ci_repos, s.test_evidence, s.repo_coverage,
    s.security_controls, s.data_handling, s.limitations, s.releases, s.publications,
  ].some(list => list.length > 0) || s.regression !== null
}

export default function PublicEvidencePage({ refreshKey }: { refreshKey: number }) {
  const showcase = useLoad(fetchShowcase, refreshKey)
  let body: ReactNode
  if (showcase.state === 'loading') body = <Loading />
  else if (showcase.state === 'error') body = <Unavailable what="Evidence content" />
  else {
    const s = showcase.data
    body = (
      <>
        {!s.available && (
          <Card><span style={{ fontSize: 13, color: 'var(--amber)' }}>Curated content is temporarily unavailable; live sections still show below.</span></Card>
        )}
        {!hasContent(s) && (
          <Card><span style={{ fontSize: 13, color: 'var(--muted)' }}>Evidence is being prepared and will appear here as it is published.</span></Card>
        )}
        <Scientific s={s} />
        <Engineering s={s} />
        <Trust s={s} />
        <History s={s} />
      </>
    )
  }
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Evidence</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Results, versions, security controls and limitations you can check for yourself.
          {showcase.state === 'ok' && showcase.data.as_of && ` Reviewed ${showcase.data.as_of}.`}
        </p>
      </div>
      {body}
    </div>
  )
}
