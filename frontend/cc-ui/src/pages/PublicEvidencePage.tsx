import type { CSSProperties, ReactNode } from 'react'
import { Card } from '../components/ui'
import {
  Badge, ComingSoon, ExtLink, Loading, Section, Unavailable, useLoad,
} from '../components/publicShowcase'
import { fetchShowcase, type Showcase } from '../publicOverview'

/**
 * Public Evidence tab (control.omnibioai.org): the material that lets a
 * visitor check the platform's claims -- benchmarks, example analyses,
 * tool versions, CI, test evidence, security controls, releases,
 * publications and known limitations. Content comes from GET /showcase:
 * a reviewed, schema-validated file plus two live sources (GitHub releases,
 * the promoted regression certification). Empty sections say so rather
 * than showing placeholder numbers.
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
      <Section title="Benchmarks" description="Pipeline results against published reference datasets.">
        {s.benchmarks.length === 0 ? <ComingSoon what="Benchmark results" /> : (
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
        )}
      </Section>

      <Section title="Example analyses" description="Real runs on public data, with inputs and reports you can inspect.">
        {s.example_runs.length === 0 ? <ComingSoon what="Example analyses" /> : (
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
        )}
      </Section>

      <Section title="Tool and database versions" description="Exact versions used by the platform's pipelines.">
        {s.tool_versions.length === 0 ? <ComingSoon what="The version list" /> : (
          <Table head={['Tool or database', 'Version', 'Category']}>
            {s.tool_versions.map(t => (
              <tr key={`${t.name}/${t.version}`}>
                <td style={TD}>{t.name}</td>
                <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{t.version}</td>
                <td style={TD}>{t.category ?? ''}</td>
              </tr>
            ))}
          </Table>
        )}
      </Section>
    </>
  )
}

function Engineering({ s }: { s: Showcase }) {
  const reg = s.regression
  return (
    <>
      <Section title="Continuous integration" description="Live build status, straight from GitHub Actions.">
        {s.ci_repos.length === 0 ? <ComingSoon what="CI status" /> : (
          <Card style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            {s.ci_repos.map(c => (
              <a key={c.repo} href={`https://github.com/${c.repo}/actions/workflows/${c.workflow}`} target="_blank" rel="noreferrer"
                style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none', color: 'var(--text2)', fontSize: 13 }}>
                <span>{c.label ?? c.repo}</span>
                <img src={`https://github.com/${c.repo}/actions/workflows/${c.workflow}/badge.svg`} alt={`${c.label ?? c.repo} CI status`} height={20} />
              </a>
            ))}
          </Card>
        )}
      </Section>

      <Section title="End-to-end certification" description="The latest promoted run of the cross-service regression suite.">
        {!reg ? <ComingSoon what="The certification summary" /> : (
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
        )}
      </Section>

      <Section title="Test runs" description="Dated results with the full outcome breakdown, not a single pass count.">
        {s.test_evidence.length === 0 ? <ComingSoon what="Dated test results" /> : (
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
        )}
      </Section>

      <Section title="Test coverage by repository" description="Measured per repository and dated; not averaged into one platform-wide figure.">
        {s.repo_coverage.length === 0 ? <ComingSoon what="Per-repository coverage" /> : (
          <Table head={['Repository', 'Coverage', 'Measured']}>
            {s.repo_coverage.map(c => (
              <tr key={c.repo}>
                <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{c.repo}</td>
                <td style={TD}>{c.coverage_pct}%</td>
                <td style={TD}>{c.date}</td>
              </tr>
            ))}
          </Table>
        )}
      </Section>
    </>
  )
}

function Trust({ s }: { s: Showcase }) {
  return (
    <>
      <Section title="Security controls" description="What is implemented today, and what is still partial.">
        {s.security_controls.length === 0 ? <ComingSoon what="The security summary" /> : (
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
        )}
      </Section>

      <Section title="Data handling">
        {s.data_handling.length === 0 ? <ComingSoon what="The data-handling statement" /> : (
          <Card>
            <ul style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {s.data_handling.map(d => <li key={d} style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5 }}>{d}</li>)}
            </ul>
          </Card>
        )}
      </Section>

      <Section title="Known limitations" description="What does not work yet, stated plainly.">
        {s.limitations.length === 0 ? <ComingSoon what="The limitations list" /> : (
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
        )}
      </Section>
    </>
  )
}

function History({ s }: { s: Showcase }) {
  return (
    <>
      <Section title="Releases">
        {s.releases.length === 0 ? <ComingSoon what="Release history" /> : (
          <Table head={['Version', 'Released']}>
            {s.releases.map(r => (
              <tr key={r.version}>
                <td style={{ ...TD, fontFamily: 'var(--mono)' }}>{r.url ? <ExtLink href={r.url}>{r.version}</ExtLink> : r.version}</td>
                <td style={TD}>{r.date ?? ''}</td>
              </tr>
            ))}
          </Table>
        )}
      </Section>

      <Section title="Publications">
        {s.publications.length === 0 ? <ComingSoon what="The publication list" /> : (
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
        )}
      </Section>
    </>
  )
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
