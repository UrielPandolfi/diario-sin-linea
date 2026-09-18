import Link from "next/link";
import type { CSSProperties } from "react";

/** Líneas que atraviesan la composición y se interrumpen: el recurso gráfico de la marca. */
const HERO_LINES = [
  { y: 72, gapStart: 470, gapEnd: 560, accent: false },
  { y: 168, gapStart: 250, gapEnd: 302, accent: false },
  { y: 264, gapStart: 706, gapEnd: 834, accent: true },
  { y: 360, gapStart: 378, gapEnd: 430, accent: false },
  { y: 456, gapStart: 902, gapEnd: 958, accent: false },
  { y: 552, gapStart: 152, gapEnd: 262, accent: false },
] as const;

const RAIL = [
  "SEÑAL",
  "SUCESO",
  "INVESTIGACIÓN",
  "AFIRMACIONES",
  "VERIFICACIÓN",
  "REDACCIÓN",
  "AUDITORÍA",
  "PUBLICADO",
] as const;

const SIGNAL_LOG = [
  { time: "14:02", label: "Publicación detectada" },
  { time: "14:03", label: "Suceso creado" },
  { time: "14:07", label: "3 fuentes contrastadas" },
  { time: "14:12", label: "2 afirmaciones respaldadas" },
  { time: "14:19", label: "Auditoría aprobada" },
  { time: "14:21", label: "Publicado", current: true },
] as const;

const META = [
  { value: "07", label: "ETAPAS ANTES DE PUBLICAR" },
  { value: "05", label: "ESTADOS DE INFORMACIÓN" },
  { value: "00", label: "CONCLUSIONES IMPUESTAS" },
] as const;

function delay(ms: number): CSSProperties {
  return { "--sl-delay": `${ms}ms` } as CSSProperties;
}

function BrokenLines() {
  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox="0 0 1200 640"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      {HERO_LINES.map((line, index) => {
        const stroke = line.accent ? "var(--accent-petrol)" : "var(--border)";
        const base = index * 130;
        return (
          <g key={line.y} opacity={line.accent ? 0.9 : 0.7}>
            <path
              d={`M0 ${line.y} H ${line.gapStart}`}
              stroke={stroke}
              strokeWidth={1}
              pathLength={1}
              className="sl-draw"
              style={{ ...delay(base), ["--sl-len" as string]: 1 }}
            />
            <path
              d={`M${line.gapEnd} ${line.y} H 1200`}
              stroke={stroke}
              strokeWidth={1}
              pathLength={1}
              className="sl-draw"
              style={{ ...delay(base + 180), ["--sl-len" as string]: 1 }}
            />
            <circle
              cx={line.gapStart}
              cy={line.y}
              r={2}
              fill={stroke}
              className="sl-fade"
              style={delay(base + 900)}
            />
            <circle
              cx={line.gapEnd}
              cy={line.y}
              r={2}
              fill={stroke}
              className="sl-fade"
              style={delay(base + 1000)}
            />
          </g>
        );
      })}
    </svg>
  );
}

function SignalPanel() {
  return (
    <aside className="hidden border border-border bg-surface px-6 py-6 lg:block" aria-label="Ejemplo de suceso">
      <div className="flex items-center justify-between gap-4">
        <p className="flex items-center gap-2.5 font-sans text-[10px] font-semibold tracking-[0.1em] text-primary">
          <span className="sl-pulse size-1.5 rounded-full bg-accent-petrol" aria-hidden />
          SUCESO EN CURSO
        </p>
        <p className="font-sans text-[10px] font-semibold tracking-[0.1em] text-secondary">EJEMPLO</p>
      </div>
      <ol className="mt-6 border-l border-border pl-5">
        {SIGNAL_LOG.map((entry, index) => (
          <li key={entry.time} className="sl-fade relative pb-4 last:pb-0" style={delay(1100 + index * 150)}>
            <span
              className={`absolute -left-[1.4375rem] top-[0.4375rem] size-1.5 rounded-full ${
                "current" in entry ? "bg-accent-ochre" : "bg-accent-petrol"
              }`}
              aria-hidden
            />
            <p className="font-sans text-[11px] font-semibold tracking-[0.06em] text-secondary">{entry.time}</p>
            <p
              className={`mt-0.5 font-sans text-[13px] ${"current" in entry ? "text-accent-ochre" : "text-primary"}`}
            >
              {entry.label}
            </p>
          </li>
        ))}
      </ol>
    </aside>
  );
}

function PipelineRail() {
  return (
    <div className="relative">
      <div className="absolute inset-x-[6.25%] top-[0.3125rem]">
        <span className="block h-px w-full bg-border" />
        <span
          className="sl-travel absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-ochre"
          aria-hidden
        />
      </div>
      <ol className="relative grid grid-cols-8">
        {RAIL.map((step, index) => (
          <li key={step} className="flex flex-col items-center gap-3 text-center">
            <span
              className={`size-2.5 rounded-full border ${
                index === RAIL.length - 1
                  ? "border-accent-petrol bg-accent-petrol"
                  : "border-border bg-background"
              }`}
              aria-hidden
            />
            <span className="hidden font-sans text-[9px] font-semibold tracking-[0.08em] text-secondary lg:block">
              {step}
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-center font-sans text-[11px] tracking-[0.06em] text-secondary lg:hidden">
        DE LA SEÑAL A LA PUBLICACIÓN
      </p>
    </div>
  );
}

export function LandingHero() {
  return (
    <section className="relative overflow-hidden border-b border-border" aria-labelledby="hero-title">
      <div className="absolute inset-0 sl-grid" aria-hidden />
      <BrokenLines />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-background" aria-hidden />

      <div className="relative mx-auto max-w-[1240px] px-5 pb-16 pt-16 md:px-8 md:pb-20 md:pt-28">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,21rem)] lg:items-end lg:gap-14">
          <div>
            <p className="sl-fade flex items-center gap-2.5 font-sans text-[10px] font-semibold tracking-[0.16em] text-accent-petrol md:text-xs">
              <span className="sl-pulse size-1.5 rounded-full bg-accent-petrol" aria-hidden />
              CÓMO FUNCIONA
            </p>

            <h1
              id="hero-title"
              className="sl-fade mt-5 font-heading text-[2.625rem] font-semibold leading-[1.06] tracking-tight text-primary md:mt-7 md:text-[3.5rem] xl:text-[4.25rem]"
              style={delay(120)}
            >
              Detectar. Contrastar.
              <span className="block text-secondary">Publicar lo que se sostiene.</span>
            </h1>

            <p
              className="sl-fade mt-6 max-w-[620px] font-sans text-[17px] leading-[27px] text-secondary md:mt-8 md:text-xl md:leading-[32px]"
              style={delay(240)}
            >
              Una noticia no empieza cuando una IA escribe un texto. Empieza cuando aparece una señal, se reúne
              evidencia y se contrasta lo que cada fuente sostiene.
            </p>

            <div className="sl-fade mt-9 flex flex-wrap items-center gap-3 md:mt-11" style={delay(360)}>
              <a
                href="#proceso"
                className="bg-accent-petrol px-5 py-3 font-sans text-sm font-medium text-[#ece8df] transition-opacity hover:opacity-90"
              >
                Ver el proceso
              </a>
              <Link
                href="/"
                className="border border-border px-5 py-3 font-sans text-sm font-medium text-primary transition-colors hover:border-accent-petrol hover:text-accent-petrol"
              >
                Ir a las noticias
              </Link>
            </div>
          </div>

          <SignalPanel />
        </div>

        <dl className="sl-fade mt-14 grid gap-6 border-t border-border pt-8 sm:grid-cols-3 md:mt-20" style={delay(480)}>
          {META.map((item) => (
            <div key={item.label}>
              <dt className="font-heading text-[2rem] font-semibold leading-none text-primary md:text-[2.5rem]">
                {item.value}
              </dt>
              <dd className="mt-2.5 font-sans text-[10px] font-semibold tracking-[0.1em] text-secondary md:text-[11px]">
                {item.label}
              </dd>
            </div>
          ))}
        </dl>

        <div className="sl-fade mt-14 md:mt-20" style={delay(600)}>
          <PipelineRail />
        </div>
      </div>
    </section>
  );
}
