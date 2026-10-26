# Seven-source credential and runtime verification

No production signing keys were generated or configured. No approved secret
manager was available. Source contract tests do not establish runtime
credentials or production acceptance.

| Source | Canonical identity | Required secret reference | Independent key stored | Runtime injection | Signature/replay/isolation at runtime |
|---|---|---|---|---|---|
| GitHub | GitHub | `DISCORD_EVENT_GITHUB_SECRET` | NO | NO | NOT_VERIFIED |
| RAG | RAG | `DISCORD_EVENT_RAG_SECRET` | NO | NO | NOT_VERIFIED |
| Workbench | Workbench | `DISCORD_EVENT_WORKBENCH_SECRET` | NO | NO | NOT_VERIFIED |
| Documentation | Documentation | `DISCORD_EVENT_DOCUMENTATION_SECRET` | NO | NO | NOT_VERIFIED |
| Video | Video | `DISCORD_EVENT_VIDEO_SECRET` | NO | NO | NOT_VERIFIED |
| Infrastructure | Infrastructure | `DISCORD_EVENT_INFRASTRUCTURE_SECRET` | NO | NO | NOT_VERIFIED |
| Support | Support | `DISCORD_EVENT_SUPPORT_SECRET` | NO | NO | NOT_VERIFIED |

Totals: `SOURCE_CREDENTIALS=0/7`, `SOURCE_PRODUCTION_CONFIGURED=0/7`,
`SOURCE_RUNTIME_QUALIFIED=0/7`. Local mocked contracts cover signing,
validation, replay defenses, and source isolation; there were no authenticated
synthetic events against seven configured production runtimes. No keys or
values are present in this report.
