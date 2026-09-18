import {
  AiStack,
  ArticleEvidenceDemo,
  AuditList,
  ClaimsDiagram,
  EventMergeDiagram,
  EventTimeline,
  RadarDiagram,
  ResearchDiagram,
  StatusGrid,
  UncertaintyDiagram,
  VerificationList,
} from "@/features/how-it-works/diagrams";
import { LandingFooter, LandingHeader } from "@/features/how-it-works/landing-chrome";
import { LandingHero } from "@/features/how-it-works/landing-hero";
import { ProcessStepper, type ProcessStep } from "@/features/how-it-works/process-stepper";
import { Reveal } from "@/features/how-it-works/reveal";
import Link from "next/link";
import type { ReactNode } from "react";

const IDEAS = [
  {
    index: "01",
    accent: "text-accent-petrol",
    title: "La unidad es el suceso",
    body: "Diez publicaciones sobre el mismo hecho no son diez noticias. Son una historia que evoluciona.",
  },
  {
    index: "02",
    accent: "text-accent-blue",
    title: "La evidencia va antes que el texto",
    body: "La IA redacta al final, sobre un suceso ya investigado y contrastado.",
  },
  {
    index: "03",
    accent: "text-accent-ochre",
    title: "El criterio es tuyo",
    body: "Te damos los hechos, las fuentes y también lo que todavía no se sabe.",
  },
] as const;

const STEPS: ProcessStep[] = [
  {
    id: "senal",
    index: "01",
    label: "SEÑAL",
    title: "Nuestro radar no rastrea Internet indiscriminadamente.",
    body: "Monitoreamos un conjunto acotado de medios, organismos, gobiernos e instituciones. Cuando uno informa algo nuevo, eso funciona como señal y recién ahí empieza la investigación.",
    note: "Una fuente encontrada durante una investigación no entra automáticamente al radar permanente.",
    visual: <RadarDiagram />,
  },
  {
    id: "suceso",
    index: "02",
    label: "SUCESO",
    title: "No pensamos en artículos. Pensamos en sucesos.",
    body: "Reunimos las señales que describen el mismo hecho y construimos una sola historia, en lugar de publicar una nota por cada versión que circula.",
    visual: <EventMergeDiagram />,
  },
  {
    id: "investigacion",
    index: "03",
    label: "INVESTIGACIÓN",
    title: "Investigamos antes de escribir.",
    body: "Buscamos la fuente oficial, los documentos públicos y lo que aportan otros medios: información nueva, confirmaciones o contradicciones.",
    visual: <ResearchDiagram />,
  },
  {
    id: "afirmaciones",
    index: "04",
    label: "AFIRMACIONES",
    title: "Separamos la noticia en afirmaciones comprobables.",
    body: "Cada afirmación que importa se evalúa por separado y se conecta con evidencia concreta.",
    visual: <ClaimsDiagram />,
  },
  {
    id: "verificacion",
    index: "05",
    label: "VERIFICACIÓN",
    title: "Verificamos cuando puede cambiar la historia.",
    body: "Ponemos atención especial en declaraciones políticas, acusaciones, leyes, decretos, estadísticas, elecciones y cifras importantes.",
    visual: <VerificationList />,
  },
  {
    id: "redaccion",
    index: "06",
    label: "REDACCIÓN",
    title: "La IA trabaja sobre evidencia, no al revés.",
    body: "Usamos inteligencia artificial para interpretar publicaciones, comparar información, detectar afirmaciones y redactar. El texto se construye a partir del estado estructurado del suceso.",
    note: "El artículo no es nuestra fuente de verdad.",
    visual: <AiStack />,
  },
  {
    id: "auditoria",
    index: "07",
    label: "AUDITORÍA",
    title: "Escribir no es el último paso.",
    body: "Antes de publicar, el borrador pasa por una auditoría que revisa nombres, cifras, fechas, atribuciones, contradicciones y lenguaje editorial.",
    visual: <AuditList />,
  },
];

const NOT_DOING = [
  "No clasificamos los hechos como positivos o negativos.",
  "No usamos orientación política como señal de ranking.",
  "No convertimos declaraciones en hechos.",
  "No ocultamos las fuentes.",
  "No fabricamos certeza cuando la evidencia no existe.",
] as const;

const PRINCIPLES = ["PRECISIÓN", "CLARIDAD", "CONTEXTO", "BREVEDAD"] as const;

function Section({
  id,
  eyebrow,
  title,
  lead,
  children,
}: {
  id?: string;
  eyebrow: string;
  title: ReactNode;
  lead?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className="border-t border-border" aria-labelledby={id ? `${id}-title` : undefined}>
      <div className="mx-auto max-w-[1240px] px-5 py-16 md:px-8 md:py-24">
        <Reveal>
          <p className="font-sans text-[10px] font-semibold tracking-[0.16em] text-accent-petrol md:text-xs">
            {eyebrow}
          </p>
          <h2
            id={id ? `${id}-title` : undefined}
            className="mt-4 max-w-[46rem] font-heading text-[1.875rem] font-semibold leading-[1.16] tracking-tight text-primary md:mt-5 md:text-[2.75rem]"
          >
            {title}
          </h2>
          {lead ? (
            <p className="mt-5 max-w-[40rem] font-sans text-[15px] leading-[25px] text-secondary md:text-[17px] md:leading-[28px]">
              {lead}
            </p>
          ) : null}
        </Reveal>
        {children}
      </div>
    </section>
  );
}

export function HowItWorksPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Sin JS el observer nunca marca las secciones como visibles. */}
      <noscript dangerouslySetInnerHTML={{ __html: "<style>.sl-reveal{opacity:1;transform:none}</style>" }} />

      <LandingHeader />

      <main>
        <LandingHero />

        <section className="border-t border-border" aria-label="Ideas centrales">
          <div className="mx-auto max-w-[1240px] px-5 md:px-8">
            <div className="grid divide-y divide-border md:grid-cols-3 md:divide-x md:divide-y-0">
              {IDEAS.map((idea, index) => (
                <Reveal key={idea.index} delay={index * 90}>
                  <div
                    className={`h-full py-10 md:py-16 ${index === 0 ? "md:pr-10" : index === 1 ? "md:px-10" : "md:pl-10"}`}
                  >
                    <p className={`font-sans text-[11px] font-semibold tracking-[0.1em] ${idea.accent}`}>
                      {idea.index}
                    </p>
                    <h2 className="mt-4 font-heading text-[1.375rem] font-semibold leading-[1.25] text-primary md:text-2xl">
                      {idea.title}
                    </h2>
                    <p className="mt-3 max-w-[24rem] font-sans text-[15px] leading-[24px] text-secondary">
                      {idea.body}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <Section
          id="proceso"
          eyebrow="EL PROCESO"
          title="Siete etapas entre una señal y una noticia publicada."
          lead="Recorré cada etapa para ver qué pasa con la información antes de que llegue a la portada."
        >
          <div className="mt-12 md:mt-16">
            <Reveal>
              <ProcessStepper steps={STEPS} />
            </Reveal>
          </div>
        </Section>

        <Section
          id="estados"
          eyebrow="ESTADOS DE LA INFORMACIÓN"
          title="No todo lo que se publica tiene el mismo respaldo."
          lead="Cada afirmación importante lleva un estado visible, para que puedas distinguir qué está sostenido y qué todavía no."
        >
          <div className="mt-12 md:mt-16">
            <Reveal>
              <StatusGrid />
            </Reveal>
          </div>

          <Reveal delay={120}>
            <div className="mt-12 grid gap-8 border-t border-border pt-12 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,32rem)] lg:items-center lg:gap-16 md:mt-16 md:pt-16">
              <div>
                <h3 className="max-w-[26rem] font-heading text-[1.625rem] font-semibold leading-[1.2] text-primary md:text-[2.125rem]">
                  “No sabemos” también es información.
                </h3>
                <p className="mt-4 max-w-[30rem] font-sans text-[15px] leading-[25px] text-secondary md:text-[17px] md:leading-[28px]">
                  Cuando las fuentes no coinciden, lo decimos. Sin Línea no elige una versión solo para poder cerrar una
                  historia.
                </p>
              </div>
              <UncertaintyDiagram />
            </div>
          </Reveal>
        </Section>

        <Section
          id="historial"
          eyebrow="DESPUÉS DE PUBLICAR"
          title="Un suceso continúa después de publicado."
          lead="No abrimos una URL nueva cada vez que aparece información material. El mismo suceso se actualiza y conserva su historial."
        >
          <div className="mt-12 md:mt-16">
            <Reveal>
              <EventTimeline />
            </Reveal>
          </div>
        </Section>

        <Section
          id="evidencia"
          eyebrow="TRAZABILIDAD"
          title="Podés ver de dónde sale la información."
          lead="Cada noticia muestra las fuentes utilizadas y el estado de las afirmaciones que importan."
        >
          <div className="mt-12 md:mt-16">
            <Reveal>
              <ArticleEvidenceDemo />
            </Reveal>
          </div>
        </Section>

        <Section id="principios" eyebrow="NUESTROS PRINCIPIOS" title="Cuatro criterios y cinco límites.">
          <Reveal>
            <ul className="mt-12 grid divide-y divide-border border-y border-border md:mt-16 md:grid-cols-4 md:divide-x md:divide-y-0">
              {PRINCIPLES.map((item, index) => (
                <li
                  key={item}
                  className={`py-7 font-heading text-[1.75rem] font-semibold leading-[1.2] md:py-9 md:text-[1.875rem] ${
                    index > 0 ? "md:pl-6" : ""
                  } ${index === 0 ? "text-primary" : "text-secondary"}`}
                >
                  {item}
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal delay={120}>
            <ul className="mt-10 grid max-w-[52rem] gap-3 md:mt-12 md:grid-cols-2 md:gap-x-10">
              {NOT_DOING.map((item) => (
                <li key={item} className="flex items-start gap-3">
                  <span className="mt-2.5 h-px w-4 shrink-0 bg-accent-ochre" aria-hidden />
                  <span className="font-sans text-[15px] leading-[25px] text-secondary">{item}</span>
                </li>
              ))}
            </ul>
          </Reveal>
        </Section>

        <section className="border-t border-border" aria-labelledby="cierre-title">
          <div className="mx-auto max-w-[1240px] px-5 py-20 md:px-8 md:py-28">
            <Reveal>
              <p className="font-sans text-[10px] font-semibold tracking-[0.16em] text-accent-ochre md:text-xs">
                LOS HECHOS. EL CRITERIO ES TUYO.
              </p>
              <h2
                id="cierre-title"
                className="mt-5 max-w-[42rem] font-heading text-[2rem] font-semibold leading-[1.12] tracking-tight text-primary md:text-[3.25rem]"
              >
                Ahora podés ver cómo aplicamos todo esto.
              </h2>
              <div className="mt-9 flex flex-wrap items-center gap-3 md:mt-11">
                <Link
                  href="/"
                  className="bg-accent-petrol px-5 py-3 font-sans text-sm font-medium text-[#ece8df] transition-opacity hover:opacity-90"
                >
                  Ver las noticias
                </Link>
                <Link
                  href="/en-vivo"
                  className="border border-border px-5 py-3 font-sans text-sm font-medium text-primary transition-colors hover:border-accent-petrol hover:text-accent-petrol"
                >
                  Sucesos en desarrollo
                </Link>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      <LandingFooter />
    </div>
  );
}
