import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ShieldCheck,
  ShieldAlert,
  ArrowLeft,
  Search,
  Download,
  FileWarning,
  FileCode2,
  AlertTriangle,
} from 'lucide-react'
import { auditRepo, exportPdf } from '../api'
import ScoutLogo from '../components/ScoutLogo'

const SEVERITY_STYLES = {
  high: 'bg-red-500/15 text-red-400 border-red-500/30',
  medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  low: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
}

function scoreColor(score) {
  if (score >= 70) return 'text-emerald-400'
  if (score >= 40) return 'text-amber-400'
  return 'text-red-400'
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-xl border border-app-border bg-app-surface p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-app-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-app-text">{value}</div>
    </div>
  )
}

export default function RepoAudit() {
  const [repoUrl, setRepoUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [report, setReport] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const handleScan = async () => {
    const url = repoUrl.trim()
    if (!url) return
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const result = await auditRepo(url)
      setReport(result)
    } catch (err) {
      setError(err.message || 'Audit failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadPdf = async () => {
    if (!report?.report_markdown) return
    setDownloading(true)
    try {
      const blob = await exportPdf(report.report_markdown, {
        title: `Repository Health Audit — ${report.repo_full_name}`,
      })
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      const safeName = report.repo_full_name.replace(/[^a-z0-9]+/gi, '_')
      link.download = `audit_${safeName}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      setError(err.message || 'PDF export failed.')
    } finally {
      setDownloading(false)
    }
  }

  const counts = report?.severity_counts || { high: 0, medium: 0, low: 0 }

  return (
    <div className="min-h-screen bg-app-bg text-app-text">
      <header className="sticky top-0 z-10 border-b border-app-border bg-app-bg/95 px-4 sm:px-8 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <ScoutLogo className="h-8 w-8 rounded-lg" />
            <div>
              <h1 className="text-lg font-semibold">Repository Health Audit</h1>
              <p className="text-xs text-app-muted">Scan an entire codebase for technical debt and debug artifacts</p>
            </div>
          </div>
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg border border-app-border px-3 py-2 text-sm text-app-muted transition-colors hover:border-primary-500/40 hover:text-app-text"
          >
            <ArrowLeft className="h-4 w-4" />
            Dashboard
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 sm:px-8 py-8">
        <div className="rounded-2xl border border-app-border bg-app-surface p-5">
          <label htmlFor="repo-url" className="mb-2 block text-sm font-medium text-app-text">
            GitHub repository URL
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              id="repo-url"
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleScan()}
              placeholder="https://github.com/owner/repo"
              className="flex-1 rounded-lg border border-app-border bg-app-bg px-4 py-3 text-sm text-app-text outline-none focus:border-primary-500/50"
            />
            <button
              type="button"
              onClick={handleScan}
              disabled={loading || !repoUrl.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent-500 px-6 py-3 text-sm font-semibold text-[#0b0f14] transition-colors hover:bg-accent-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Scanning...
                </>
              ) : (
                <>
                  <Search className="h-4 w-4" />
                  Scan repository
                </>
              )}
            </button>
          </div>
          {error && (
            <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
        </div>

        {report && (
          <div className="mt-8 space-y-6">
            <div
              className={`flex flex-col gap-4 rounded-2xl border-2 p-6 sm:flex-row sm:items-center sm:justify-between ${
                report.gate_passed ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-red-500/40 bg-red-500/10'
              }`}
            >
              <div className="flex items-center gap-4">
                {report.gate_passed ? (
                  <ShieldCheck className="h-12 w-12 text-emerald-400" />
                ) : (
                  <ShieldAlert className="h-12 w-12 text-red-400" />
                )}
                <div>
                  <div className="text-sm text-app-muted">{report.repo_full_name}</div>
                  <h2 className={`text-2xl font-bold ${report.gate_passed ? 'text-emerald-300' : 'text-red-300'}`}>
                    Gate {report.gate_passed ? 'PASSED' : 'FAILED'}
                  </h2>
                  <p className="text-sm text-app-muted">{report.summary}</p>
                </div>
              </div>
              <div className="text-left sm:text-right">
                <div className={`text-5xl font-bold ${scoreColor(report.readiness_score)}`}>
                  {report.readiness_score}
                </div>
                <div className="text-sm text-app-muted">/ 100 readiness</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="Technical debt" value={report.technical_debt} />
              <StatCard label="Files scanned" value={report.files_scanned} />
              <StatCard label="Lines scanned" value={report.lines_scanned} />
              <StatCard label="Threshold" value={`${report.readiness_threshold}/100`} />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4">
                <div className="flex items-center gap-2 text-red-400">
                  <FileWarning className="h-4 w-4" />
                  <span className="text-sm font-semibold">High severity</span>
                </div>
                <div className="mt-2 text-3xl font-bold text-app-text">{counts.high}</div>
              </div>
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="flex items-center gap-2 text-amber-400">
                  <FileWarning className="h-4 w-4" />
                  <span className="text-sm font-semibold">Medium severity</span>
                </div>
                <div className="mt-2 text-3xl font-bold text-app-text">{counts.medium}</div>
              </div>
              <div className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-4">
                <div className="flex items-center gap-2 text-sky-400">
                  <FileCode2 className="h-4 w-4" />
                  <span className="text-sm font-semibold">Low severity</span>
                </div>
                <div className="mt-2 text-3xl font-bold text-app-text">{counts.low}</div>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleDownloadPdf}
                disabled={downloading}
                className="inline-flex items-center gap-2 rounded-lg border border-app-border px-4 py-2 text-sm font-medium text-app-text transition-colors hover:border-primary-500/40 hover:bg-app-elevated disabled:opacity-50"
              >
                <Download className="h-4 w-4" />
                {downloading ? 'Preparing PDF...' : 'Download PDF report'}
              </button>
            </div>

            {report.top_files?.length > 0 && (
              <section>
                <h3 className="mb-3 text-lg font-semibold">Files with the most findings</h3>
                <div className="overflow-hidden rounded-xl border border-app-border">
                  <table className="w-full text-sm">
                    <thead className="bg-app-elevated/60 text-app-muted">
                      <tr>
                        <th className="px-4 py-2 text-left font-medium">File</th>
                        <th className="px-4 py-2 text-right font-medium">Issues</th>
                        <th className="px-4 py-2 text-right font-medium">High</th>
                        <th className="px-4 py-2 text-right font-medium">Medium</th>
                        <th className="px-4 py-2 text-right font-medium">Low</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.top_files.map((file) => (
                        <tr key={file.file_path} className="border-t border-app-border">
                          <td className="px-4 py-2 font-mono text-xs text-app-text break-all">{file.file_path}</td>
                          <td className="px-4 py-2 text-right text-app-text">{file.issue_count}</td>
                          <td className="px-4 py-2 text-right text-red-400">{file.high}</td>
                          <td className="px-4 py-2 text-right text-amber-400">{file.medium}</td>
                          <td className="px-4 py-2 text-right text-sky-400">{file.low}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {report.findings?.length > 0 && (
              <section>
                <h3 className="mb-3 text-lg font-semibold">
                  Findings
                  {report.findings_truncated && (
                    <span className="ml-2 text-sm font-normal text-app-muted">
                      (showing first {report.findings.length} of {report.technical_debt})
                    </span>
                  )}
                </h3>
                <div className="space-y-2">
                  {report.findings.map((finding, idx) => (
                    <div
                      key={`${finding.file_path}-${finding.line_number}-${idx}`}
                      className="flex flex-col gap-1 rounded-lg border border-app-border bg-app-surface p-3 sm:flex-row sm:items-center sm:gap-3"
                    >
                      <span
                        className={`inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
                          SEVERITY_STYLES[finding.severity] || SEVERITY_STYLES.low
                        }`}
                      >
                        {finding.severity} · {finding.category}
                      </span>
                      <span className="font-mono text-xs text-app-muted break-all">
                        {finding.file_path}:{finding.line_number}
                      </span>
                      <code className="flex-1 truncate font-mono text-xs text-app-text">{finding.snippet}</code>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
