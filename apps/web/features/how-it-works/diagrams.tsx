const PANEL = "border border-border bg-surface";

const SOURCES = ["Rosario3", "La Capital", "Gobierno", "Agencia"] as const;

const RESEARCH_LANES = [
  { label: "MEDIO QUE LO PUBLICÓ", question: "¿Qué informó?", official: false },
  { label: "FUENTE OFICIAL", question: "¿Qué anunció realmente?", official: true },
  { label: "OTROS MEDIOS", question: "¿Qué información adicional aportan?", official: false },
  { label: "DOCUMENTOS", question: "¿Existe resolución, decreto o dato público?", official: false },
] as const;

const CLAIMS = [
  { id: "01", text: "El Gobierno anunció una reducción de tarifas.", status: "RESPALDADO", tone: "petrol" },
  { id: "02", text: "La reducción anunciada sería del 15%.", status: "RESPALDADO", tone: "petrol" },
  { id: "03", text: "Entraría en vigencia en octubre.", status: "FUENTE ÚNICA", tone: "ochre" },
  { id: "04", text: "Alcanzaría a 4 millones de hogares.", status: "ATRIBUIDO", tone: "blue" },
] as const;

const STATES = [
  { label: "RESPALDADO", tone: "petrol", text: "Varias evidencias compatibles la sostienen." },
  { label: "FUENTE ÚNICA", tone: "ochre", text: "Por ahora proviene de una sola fuente relevante." },
  { label: "EN DISPUTA", tone: "blue", text: "Distintas fuentes sostienen versiones incompatibles." },
  { label: "CONTRADICHO", tone: "muted", text: "Evidencia sólida contradice la afirmación." },
  { label: "CHEQUEADO", tone: "petrol", text: "Sin Línea hizo una verificación adicional." },
] as const;

const VERIFY_ITEMS = [
  "Declaraciones políticas",
  "Leyes y decretos",
  "Estadísticas y elecciones",
  "Acusaciones y responsabilidades",
  "Cifras y documentos públicos",
] as const;

const AI_STEPS = ["FUENTES", "EVIDENCIA", "CLAIMS", "CONTEXTO", "IA REDACTA", "AUDITORÍA"] as const;

const AUDIT_ITEMS = [
  "nombres",
  "cifras",
  "fechas",
  "atribuciones",
  "contradicciones",
  "afirmaciones sin respaldo",
  "lenguaje editorial",
] as const;

const TIMELINE = [
  { time: "14:00", label: "Incendio detectado", current: false },
  { time: "14:12", label: "Calle cortada", current: false },
  { time: "14:23", label: "Bomberos confirma que no hay heridos", current: false },
  { time: "14:57", label: "Causa preliminar", current: true },
] as const;

const EVIDENCE_SOURCES = ["Boletín Oficial", "Ministerio de Economía", "Medio independiente"] as const;

function statusClass(tone: "petrol" | "ochre" | "blue" | "muted"): string {
  if (tone === "ochre") return "text-accent-ochre";
  if (tone === "blue") return "text-accent-blue";
  if (tone === "muted") return "text-secondary";
  return "text-accent-petrol";
}

function pillBorder(tone: "petrol" | "ochre" | "blue" | "muted"): string {
  if (tone === "ochre") return "border-accent-ochre text-accent-ochre";
  if (tone === "blue") return "border-accent-blue text-accent-blue";
  if (tone === "muted") return "border-secondary text-secondary";
  return "border-accent-petrol text-accent-petrol";
}

export function EventMergeDiagram() {
  return (
    <>
      <div className="grid grid-cols-2 items-stretch gap-x-4 gap-y-2 md:hidden">
        <ul className="flex flex-col gap-2">
          {SOURCES.map((name) => (
            <li
              key={name}
              className={`${PANEL} flex h-[2.625rem] items-center rounded-xl px-3 font-sans text-[13px] font-medium text-primary`}
            >
              {name}
            </li>
          ))}
        </ul>
        <div className={`${PANEL} flex flex-col justify-start rounded-[0.875rem] border-accent-petrol px-4 py-[1.375rem]`}>
          <p className="font-sans text-[10px] font-semibold tracking-[0.06em] text-accent-petrol">UN SUCESO</p>
          <p className="mt-4 font-heading text-xl font-semibold leading-[1.7rem] text-primary">
            Una historia que evoluciona
          </p>
        </div>
      </div>

      <div className="hidden items-stretch md:grid md:grid-cols-[minmax(0,13.125rem)_minmax(2rem,5.625rem)_minmax(9rem,11.875rem)]">
        <ul className="flex flex-col gap-7">
          {SOURCES.map((name) => (
            <li
              key={name}
              className={`${PANEL} flex h-[3.375rem] items-center rounded-[0.625rem] px-4 font-sans text-sm font-medium text-primary`}
            >
              {name}
            </li>
          ))}
        </ul>
        <div className="flex flex-col justify-around py-[1.625rem]" aria-hidden>
          {SOURCES.map((name) => (
            <div key={name} className="h-0.5 bg-border" />
          ))}
        </div>
        <div className="flex items-center">
          <div
            className={`${PANEL} relative flex h-[8.125rem] w-full flex-col justify-start overflow-hidden rounded-[1.125rem] border-accent-petrol px-7 pt-8`}
          >
            <p className="font-sans text-xs font-semibold tracking-[0.06em] text-accent-petrol">UN SUCESO</p>
            <p className="mt-2 font-heading text-xl font-semibold leading-[1.625rem] text-primary">
              Una historia que evoluciona
            </p>
            <span className="absolute inset-x-0 bottom-0 h-[0.1875rem] bg-accent-petrol" aria-hidden />
          </div>
        </div>
      </div>
    </>
  );
}

export function RadarDiagram() {
  return (
    <div className={`${PANEL} max-w-[26rem] rounded-[0.875rem] px-[1.125rem] py-[1.125rem] md:rounded-[1.125rem] md:px-7 md:py-7`}>
      <p className="font-sans text-[10px] font-semibold tracking-[0.08em] text-accent-blue md:text-xs">
        FUENTES VIGILADAS
      </p>
      <ul className="mt-6 grid grid-cols-2 gap-2.5 md:mt-8 md:gap-4">
        {["Medios", "Organismos", "Gobiernos", "Instituciones"].map((item) => (
          <li
            key={item}
            className="flex h-9 items-center rounded-lg border border-border bg-background px-2.5 font-sans text-xs font-medium text-primary md:h-11 md:px-3.5 md:text-[13px]"
          >
            {item}
          </li>
        ))}
      </ul>
      <p className="mt-4 text-center font-sans text-lg text-secondary md:mt-5 md:text-[1.375rem]" aria-hidden>
        ↓
      </p>
      <p className="mt-1 text-center font-sans text-[10px] font-semibold tracking-[0.08em] text-accent-ochre md:text-xs">
        SEÑAL NUEVA
      </p>
    </div>
  );
}

export function ResearchDiagram() {
  return (
    <div className="space-y-3.5 md:space-y-5">
      <div className={`${PANEL} rounded-xl px-4 py-4 md:rounded-[0.875rem] md:px-[1.625rem] md:py-[1.375rem]`}>
        <p className="font-sans text-[10px] font-semibold tracking-[0.08em] text-accent-ochre md:text-[11px]">
          SE DETECTA
        </p>
        <p className="mt-2 font-heading text-lg font-semibold leading-6 text-primary md:mt-3 md:text-2xl md:leading-[1.9375rem]">
          “El Gobierno anunció cambios en las tarifas eléctricas.”
        </p>
      </div>
      <ul className="grid gap-2.5 sm:grid-cols-2 md:gap-4">
        {RESEARCH_LANES.map((lane) => (
          <li key={lane.label} className={`${PANEL} rounded-xl px-3.5 py-3.5 md:rounded-[0.875rem] md:px-5 md:py-5`}>
            <p
              className={`font-sans text-[9px] font-semibold tracking-[0.08em] md:text-[11px] ${
                lane.official ? "text-accent-petrol" : "text-secondary"
              }`}
            >
              {lane.label}
            </p>
            <p className="mt-3 font-sans text-sm font-medium leading-5 text-primary md:mt-4 md:text-[17px] md:leading-[1.5625rem]">
              {lane.question}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ClaimsDiagram() {
  return (
    <div className="space-y-2.5">
      <div className={`${PANEL} rounded-xl px-3.5 py-3.5 md:rounded-[0.875rem] md:px-6 md:py-5`}>
        <p className="font-sans text-[10px] font-semibold tracking-[0.08em] text-secondary md:text-[11px]">
          PUBLICACIÓN
        </p>
        <p className="mt-2 font-sans text-[15px] leading-6 text-primary md:mt-3 md:text-lg md:leading-[1.75rem]">
          El Gobierno anunció que reducirá las tarifas un 15% desde octubre y aseguró que la medida beneficiará a 4
          millones de hogares.
        </p>
      </div>
      <ol className="space-y-2">
        {CLAIMS.map((claim) => (
          <li
            key={claim.id}
            className={`${PANEL} flex items-start gap-3 rounded-xl px-3.5 py-3.5 md:px-[1.125rem] md:py-4`}
          >
            <span className="font-sans text-xs font-semibold leading-5 text-secondary">{claim.id}</span>
            <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
              <p className="font-sans text-[15px] font-medium leading-5 text-primary md:text-base md:leading-6">
                {claim.text}
              </p>
              <p
                className={`shrink-0 font-sans text-[11px] font-semibold tracking-[0.08em] ${statusClass(claim.tone)}`}
              >
                {claim.status}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function StatusGrid() {
  return (
    <ul className="grid gap-2.5 sm:grid-cols-2 md:gap-4 xl:grid-cols-3">
      {STATES.map((state) => (
        <li key={state.label} className={`${PANEL} rounded-[0.875rem] px-4 py-4 md:px-[1.125rem] md:py-[1.125rem]`}>
          <p
            className={`inline-flex h-7 items-center rounded-full border bg-background px-3 font-sans text-[10px] font-semibold tracking-[0.06em] ${pillBorder(state.tone)}`}
          >
            {state.label}
          </p>
          <p className="mt-3 font-sans text-sm leading-5 text-secondary md:mt-4 md:leading-[1.375rem]">{state.text}</p>
        </li>
      ))}
    </ul>
  );
}

export function UncertaintyDiagram() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 md:gap-4">
        <div className={`${PANEL} rounded-[0.875rem] px-3 py-3 md:px-[1.125rem] md:py-[1.125rem]`}>
          <p className="font-sans text-[10px] font-semibold tracking-[0.08em] text-secondary">FUENTE A</p>
          <p className="mt-2 font-heading text-xl font-semibold leading-7 text-primary md:text-[1.3125rem]">
            200 personas
          </p>
        </div>
        <p className="font-sans text-xl text-accent-ochre md:text-[1.875rem] md:leading-[2.125rem]" aria-hidden>
          ≠
        </p>
        <div className={`${PANEL} rounded-[0.875rem] px-3 py-3 md:px-[1.125rem] md:py-[1.125rem]`}>
          <p className="font-sans text-[10px] font-semibold tracking-[0.08em] text-secondary">FUENTE B</p>
          <p className="mt-2 font-heading text-xl font-semibold leading-7 text-primary md:text-[1.3125rem]">
            600 personas
          </p>
        </div>
      </div>
      <div className={`${PANEL} rounded-[0.875rem] border-accent-ochre px-3.5 py-3.5 md:px-5 md:py-5`}>
        <p className="font-sans text-[11px] font-semibold tracking-[0.08em] text-accent-ochre">EN DISPUTA</p>
        <p className="mt-2 font-sans text-sm leading-[1.375rem] text-primary md:text-base md:leading-[1.5625rem]">
          No existe información independiente suficiente para resolver la diferencia.
        </p>
      </div>
    </div>
  );
}

export function VerificationList() {
  return (
    <div className="max-w-[34rem]">
      <ul className={`${PANEL} grid gap-3.5 rounded-2xl px-4 py-6 sm:grid-cols-2 md:px-7 md:py-7`}>
        {VERIFY_ITEMS.map((item) => (
          <li key={item} className="flex items-center gap-3">
            <span className="size-2 shrink-0 rounded-full bg-accent-petrol" aria-hidden />
            <span className="font-sans text-sm font-medium text-primary">{item}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 font-sans text-sm leading-[1.375rem] text-secondary md:mt-5">
        No verificamos cada frase por rutina. El esfuerzo se concentra donde puede cambiar la comprensión del hecho.
      </p>
    </div>
  );
}

export function AiStack() {
  return (
    <ol className="w-full max-w-[18.75rem] space-y-0">
      {AI_STEPS.map((step, index) => (
        <li key={step} className="flex flex-col items-center">
          <div
            className={`${PANEL} flex h-[2.625rem] w-full items-center rounded-[0.625rem] px-3.5 md:h-12 ${
              step === "IA REDACTA" ? "border-accent-blue text-accent-blue" : "text-primary"
            }`}
          >
            <span className="font-sans text-[11px] font-semibold tracking-[0.08em] md:text-xs">{step}</span>
          </div>
          {index < AI_STEPS.length - 1 ? (
            <span className="py-0.5 font-sans text-lg leading-5 text-secondary" aria-hidden>
              ↓
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function AuditList() {
  return (
    <div className={`${PANEL} max-w-[26rem] rounded-2xl px-4 py-5 md:px-6 md:py-6`}>
      <p className="font-sans text-[11px] font-semibold tracking-[0.08em] text-accent-ochre">AUDITORÍA</p>
      <ul className="mt-4 space-y-2">
        {AUDIT_ITEMS.map((item) => (
          <li key={item} className="flex items-center gap-2">
            <span className="w-5 font-sans text-[13px] font-semibold text-accent-petrol" aria-hidden>
              ✓
            </span>
            <span className="font-sans text-[13px] text-primary">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EventTimeline() {
  return (
    <>
      <ol className="relative ml-1.5 border-l border-border pl-6 md:hidden">
        {TIMELINE.map((item) => (
          <li key={item.time} className="relative pb-6 last:pb-0">
            <span
              className={`absolute -left-[1.9375rem] top-1 size-[0.5625rem] rounded-full ${
                item.current ? "bg-accent-ochre" : "bg-accent-petrol"
              }`}
              aria-hidden
            />
            <p className="font-sans text-[13px] font-semibold text-primary">{item.time}</p>
            <p className="mt-0.5 font-sans text-sm text-secondary">{item.label}</p>
          </li>
        ))}
      </ol>
      <div className="hidden md:block">
        <div className="relative pt-1">
          <div className="absolute left-1.5 right-8 top-[0.4375rem] h-[0.1875rem] bg-border" aria-hidden />
          <ol className="grid grid-cols-4 gap-3">
            {TIMELINE.map((item) => (
              <li key={item.time}>
                <span
                  className={`relative z-[1] mb-3 block size-3 rounded-full ${
                    item.current ? "bg-accent-ochre" : "bg-accent-petrol"
                  }`}
                  aria-hidden
                />
                <p className="font-sans text-xs font-semibold text-primary">{item.time}</p>
                <p className="mt-1 max-w-[9rem] font-sans text-xs leading-[1.125rem] text-secondary">{item.label}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </>
  );
}

export function ArticleEvidenceDemo() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(16rem,23.75rem)] lg:items-start lg:gap-6">
      <article className={`${PANEL} rounded-2xl px-3.5 py-4 md:px-6 md:py-6`}>
        <p className="font-sans text-[10px] font-semibold tracking-[0.12em] text-secondary">
          ARGENTINA · ACTUALIZADO HACE 8 MIN
        </p>
        <h3 className="mt-3 font-heading text-xl font-semibold leading-7 text-primary md:text-[1.625rem] md:leading-[2.125rem]">
          El Gobierno anunció cambios en las tarifas eléctricas desde octubre
        </h3>
        <p className="mt-4 font-sans text-sm leading-[1.375rem] text-primary md:text-base md:leading-[1.625rem]">
          La medida contempla una reducción anunciada del 15% y entraría en vigencia en octubre.
        </p>
        <p className="mt-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-accent-petrol bg-background px-2.5 py-3 md:max-w-[31.25rem] md:px-3.5">
          <span className="font-sans text-[13px] font-medium text-primary md:text-sm">
            “reducción anunciada del 15%”
          </span>
          <span className="font-sans text-[10px] font-semibold tracking-[0.08em] text-accent-petrol">RESPALDADO</span>
        </p>
        <p className="mt-6 font-sans text-[13px] leading-5 text-secondary">
          Fuentes utilizadas: Boletín Oficial · Ministerio · medios consultados
        </p>
      </article>
      <aside className={`${PANEL} rounded-2xl border-accent-petrol px-3.5 py-4 md:px-[1.375rem] md:py-[1.375rem]`}>
        <p className="font-sans text-[11px] font-semibold tracking-[0.08em] text-accent-petrol">RESPALDADO POR</p>
        <ul className="mt-4">
          {EVIDENCE_SOURCES.map((source, index) => (
            <li
              key={source}
              className={`font-sans text-[15px] font-medium leading-[1.3125rem] text-primary ${
                index > 0 ? "mt-3 border-t border-border pt-3" : ""
              }`}
            >
              {source}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
