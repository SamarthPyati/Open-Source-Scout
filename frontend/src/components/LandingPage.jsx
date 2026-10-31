import { useNavigate } from 'react-router-dom'
import {
  Rocket,
  ClipboardList,
  Search,
  BarChart2,
  MapPin,
  FileText,
  File,
  Sparkles,
  Star,
} from 'lucide-react'
import ScoutLogo from './ScoutLogo'

export default function LandingPage() {
  const navigate = useNavigate()

  const btnPrimary =
    'inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 text-sm font-semibold text-[#0B0F14] bg-[#22C55E] shadow-[0_0_0_1px_rgba(34,197,94,0.25),0_8px_24px_-4px_rgba(34,197,94,0.35)] transition-all duration-200 ease-out hover:bg-[#16A34A] hover:-translate-y-0.5 hover:shadow-[0_0_0_1px_rgba(34,197,94,0.35),0_12px_28px_-4px_rgba(34,197,94,0.4)] active:translate-y-0'

  const navLink =
    'text-sm text-[#9DA7B3] transition-colors duration-200 hover:text-[#E6EDF3]'

  return (
    <div className="landing-page-root min-h-screen font-sans text-[#E6EDF3] selection:bg-[#3B82F6]/30 selection:text-[#E6EDF3]">
      <header className="sticky top-0 z-20 border-b border-[#1F2937] bg-[#0B0F14]/80 backdrop-blur-md px-4 sm:px-8 py-4">
        <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <ScoutLogo className="h-8 w-8 rounded-lg shadow-lg shadow-black/20" />
            <span className="font-semibold text-[#E6EDF3] tracking-tight">Open Source Scout</span>
          </div>
          <nav className="hidden md:flex items-center gap-8">
            <a href="#features" className={navLink}>
              Features
            </a>
            <a href="#how-it-works" className={navLink}>
              How it works
            </a>
            <a href="#ecosystem" className={navLink}>
              Ecosystem
            </a>
          </nav>
          <div className="flex items-center gap-3 sm:gap-4">
            <button
              type="button"
              onClick={() => navigate('/login')}
              className={`${navLink} px-2 py-1.5 rounded-md hover:bg-[#111827]`}
            >
              Log In
            </button>
            <button
              type="button"
              onClick={() => navigate('/signup')}
              className="rounded-lg px-4 py-2 text-sm font-semibold text-[#0B0F14] bg-[#22C55E] transition-all duration-200 ease-out hover:bg-[#16A34A] hover:-translate-y-0.5 shadow-[0_0_0_1px_rgba(34,197,94,0.2),0_4px_14px_-2px_rgba(34,197,94,0.3)] active:translate-y-0"
            >
              Sign Up
            </button>
          </div>
        </div>
      </header>

      <section className="relative px-4 sm:px-8 pt-16 pb-24 sm:pt-20 sm:pb-28 overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0 opacity-90"
          aria-hidden
          style={{
            background:
              'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(59, 130, 246, 0.08), transparent 65%)',
          }}
        />
        <div className="relative max-w-6xl mx-auto flex flex-col lg:flex-row items-center gap-14 lg:gap-12">
          <div className="flex-1 w-full landing-hero-animate">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#1F2937] bg-[#111827]/90 px-3 py-1.5 text-xs font-medium text-[#9DA7B3] mb-8">
              <Sparkles className="w-3.5 h-3.5 text-[#60A5FA]" />
              <span className="tracking-wide text-[#E6EDF3]/90">NEW · AI-POWERED CONTRIBUTION PATHS</span>
            </div>

            <div className="relative isolate">
              <div
                aria-hidden
                className="pointer-events-none absolute -inset-x-6 -inset-y-8 sm:-inset-x-10 sm:-inset-y-12 -z-10"
                style={{
                  background:
                    'radial-gradient(circle at 30% 50%, rgba(59,130,246,0.15), transparent 40%)',
                }}
              />
              <h1 className="relative text-4xl sm:text-5xl lg:text-[3.25rem] font-bold tracking-tight text-[#E6EDF3] leading-[1.12] sm:leading-[1.1] space-y-1 sm:space-y-2">
                <span className="block pb-1 sm:pb-2">
                  <span className="text-[#9DA7B3] font-semibold">From</span>{' '}
                  <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#3B82F6] to-[#60A5FA]">
                    confused
                  </span>
                </span>
                <span className="block pb-1 sm:pb-2">
                  <span className="text-[#9DA7B3] font-semibold">to</span>{' '}
                  <span className="text-[#E6EDF3]">contributor</span>
                </span>
                <span className="block pt-2 sm:pt-3 text-3xl sm:text-4xl lg:text-[2.75rem] font-extrabold text-[#22C55E] drop-shadow-[0_0_32px_rgba(34,197,94,0.25)]">
                  Ship your first real PR — faster.
                </span>
              </h1>
            </div>

            <p className="mt-8 text-lg text-[#9DA7B3] max-w-lg leading-relaxed">
              Navigate unfamiliar codebases, understand what actually matters, and go from issue to commit with{' '}
              <span className="text-[#E6EDF3]">clarity</span> — not guesswork.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-4">
              <button type="button" onClick={() => navigate('/dashboard')} className={btnPrimary}>
                Get started free
              </button>
            </div>
          </div>

          <div className="flex-1 w-full max-w-xl lg:max-w-none landing-hero-animate-delay">
            <div
              className="landing-code-card rounded-[10px] border border-[#1F2937] bg-[#111827] p-5 sm:p-6 rotate-0 sm:rotate-[1.5deg]"
              style={{ borderRadius: '10px' }}
            >
              <div className="flex gap-2 mb-5">
                <span className="h-3 w-3 rounded-full bg-[#FF5F57]/90" />
                <span className="h-3 w-3 rounded-full bg-[#FEBC2E]/90" />
                <span className="h-3 w-3 rounded-full bg-[#28C840]/90" />
              </div>
              <div className="flex items-center justify-between gap-2 mb-4 pb-3 border-b border-[#1F2937]">
                <span className="font-mono text-xs text-[#9DA7B3]">src/config/client.ts</span>
                <span className="text-[10px] uppercase tracking-wider text-[#3B82F6] font-medium">AI suggestion</span>
              </div>
              <pre className="font-mono text-[11px] sm:text-xs leading-6 text-[#9DA7B3] overflow-x-auto">
                <code className="block space-y-0.5">
                  <span className="block text-[#9DA7B3]/80">{'// Retry policy — tuned for flaky CI'}</span>
                  <span className="block h-1.5" />
                  <span className="flex rounded bg-[#EF4444]/12 text-[#EF4444] pl-2 -mx-1 py-0.5 border-l-2 border-[#EF4444]">
                    <span className="select-none pr-2 opacity-70">−</span>
                    <span>
                      <span className="text-[#E6EDF3]/90">export const </span>
                      DEFAULT_TIMEOUT = <span className="text-[#FBBF24]">5000</span>;
                    </span>
                  </span>
                  <span className="flex rounded bg-[#22C55E]/12 text-[#22C55E] pl-2 -mx-1 py-0.5 border-l-2 border-[#22C55E] ring-1 ring-inset ring-[#3B82F6]/25">
                    <span className="select-none pr-2 opacity-70">+</span>
                    <span>
                      <span className="text-[#E6EDF3]/90">export const </span>
                      DEFAULT_TIMEOUT = <span className="text-[#FBBF24]">15000</span>;{' '}
                      <span className="text-[#9DA7B3]">{'// match upstream'}</span>
                    </span>
                  </span>
                  <span className="block h-2" />
                  <span className="block text-[#9DA7B3]/70">{'await fetchIssues(repo, {'}</span>
                  <span className="block text-[#E6EDF3] pl-4">
                    <span className="text-[#60A5FA]">timeout</span>: DEFAULT_TIMEOUT,
                  </span>
                  <span className="block text-[#9DA7B3]/70">{'});'}</span>
                </code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="px-4 sm:px-8 py-20 border-t border-[#1F2937]">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#E6EDF3] tracking-tight mb-2">Choose your path</h2>
          <p className="text-[#9DA7B3] text-lg mb-12 max-w-2xl">
            Tailored flows whether you already have a repo in mind or want discovery by stack.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 lg:gap-8">
            <div
              role="button"
              tabIndex={0}
              onClick={() => navigate('/dashboard?mode=repo')}
              onKeyDown={(e) => e.key === 'Enter' && navigate('/dashboard?mode=repo')}
              className="group rounded-xl border border-[#1F2937] bg-[#111827] p-8 cursor-pointer transition-all duration-200 ease-out hover:border-[#3B82F6]/50 hover:-translate-y-0.5 hover:shadow-[0_20px_40px_-16px_rgba(0,0,0,0.5)]"
            >
              <h3 className="text-xl font-semibold text-[#E6EDF3] mb-2 flex items-center gap-2">
                I have a repository
                <ClipboardList className="w-5 h-5 text-[#60A5FA]" />
              </h3>
              <p className="text-[#9DA7B3] mb-5 leading-relaxed">
                Index your codebase for AI-guided onboarding, clearer issues, and contribution paths new devs can follow.
              </p>
              <span className="text-[#3B82F6] font-medium inline-flex items-center gap-1 transition-all duration-200 group-hover:gap-2 group-hover:text-[#60A5FA]">
                Setup indexing <span aria-hidden>→</span>
              </span>
            </div>

            <div
              role="button"
              tabIndex={0}
              onClick={() => navigate('/dashboard?mode=tech')}
              onKeyDown={(e) => e.key === 'Enter' && navigate('/dashboard?mode=tech')}
              className="group rounded-xl border border-[#1F2937] bg-[#111827] p-8 cursor-pointer transition-all duration-200 ease-out hover:border-[#3B82F6]/50 hover:-translate-y-0.5 hover:shadow-[0_20px_40px_-16px_rgba(0,0,0,0.5)]"
            >
              <h3 className="text-xl font-semibold text-[#E6EDF3] mb-2 flex items-center gap-2">
                Find repos by my skills
                <Search className="w-5 h-5 text-[#60A5FA]" />
              </h3>
              <p className="text-[#9DA7B3] mb-5 leading-relaxed">
                Match your stack to high-signal issues across vetted open source projects — without endless scrolling.
              </p>
              <span className="text-[#3B82F6] font-medium inline-flex items-center gap-1 transition-all duration-200 group-hover:gap-2 group-hover:text-[#60A5FA]">
                Discover projects <span aria-hidden>→</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="px-4 sm:px-8 py-20 bg-[#0B0F14] border-t border-[#1F2937]">
        <div className="max-w-6xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-[#E6EDF3] tracking-tight mb-2">Streamline your workflow</h2>
          <p className="text-[#9DA7B3] text-lg mb-14 max-w-2xl mx-auto">
            Less friction from “interesting issue” to merged PR.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 text-left">
            {[
              {
                Icon: BarChart2,
                title: 'Smart issue ranking',
                body: 'Prioritize by fit, complexity, and impact — tuned to how you actually work.',
              },
              {
                Icon: MapPin,
                title: 'Code location',
                body: 'Skip the treasure hunt. We surface files and lines worth your attention.',
              },
              {
                Icon: FileText,
                title: 'PR-ready briefs',
                body: 'Clear, technical narratives maintainers want — structure, tests, and context.',
              },
              {
                Icon: File,
                title: 'Export to PDF',
                body: 'Save guides for offline review or sharing with your team.',
              },
            ].map(({ Icon, title, body }) => (
              <div
                key={title}
                className="rounded-xl border border-[#1F2937] bg-[#111827] p-6 transition-all duration-200 ease-out hover:border-[#1F2937] hover:shadow-lg hover:-translate-y-0.5"
              >
                <div className="w-10 h-10 rounded-lg bg-[#3B82F6]/15 border border-[#3B82F6]/25 flex items-center justify-center mb-4">
                  <Icon className="w-5 h-5 text-[#60A5FA]" />
                </div>
                <h3 className="font-semibold text-[#E6EDF3] mb-2">{title}</h3>
                <p className="text-[#9DA7B3] text-sm leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="ecosystem" className="px-4 sm:px-8 py-16 border-t border-[#1F2937]">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6 rounded-xl border border-[#1F2937] bg-[#111827] px-6 py-8">
          <div>
            <h2 className="text-xl font-semibold text-[#E6EDF3] mb-1">Built for the open source ecosystem</h2>
            <p className="text-[#9DA7B3] text-sm max-w-xl">
              Works alongside GitHub workflows — we help you focus, not replace your stack.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            className={`${btnPrimary} shrink-0 px-5 py-2.5 text-sm`}
          >
            Open app
            <Rocket className="w-4 h-4" />
          </button>
        </div>
      </section>

      <footer className="px-4 sm:px-8 py-8 border-t border-[#1F2937] bg-[#0B0F14]">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2 text-[#9DA7B3] text-sm">
            <ScoutLogo className="h-6 w-6 rounded-md" />
            <span>Open Source Scout © {new Date().getFullYear()}</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-6">
            <a href="#" className="text-sm text-[#9DA7B3] transition-colors duration-200 hover:text-[#E6EDF3]">
              Privacy
            </a>
            <a href="#" className="text-sm text-[#9DA7B3] transition-colors duration-200 hover:text-[#E6EDF3]">
              Terms
            </a>
            <a href="#" className="text-sm text-[#9DA7B3] transition-colors duration-200 hover:text-[#E6EDF3]">
              Status
            </a>
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-[#1F2937] bg-[#111827] px-4 py-2 text-sm text-[#E6EDF3] transition-all duration-200 ease-out hover:border-[#3B82F6] hover:text-[#60A5FA] hover:-translate-y-0.5"
            >
              <Star className="w-4 h-4 text-[#FBBF24]" />
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
