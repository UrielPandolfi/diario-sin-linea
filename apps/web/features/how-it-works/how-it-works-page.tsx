import {
  AiStack,
  ArticleEvidenceDemo,
  AuditList,
  ClaimsDiagram,
  EventMergeDiagram,
  EventTimeline,
  PipelineStrip,
  Principles,
  RadarDiagram,
  ResearchDiagram,
  StatusGrid,
  UncertaintyDiagram,
  VerificationList,
} from "@/features/how-it-works/diagrams";
import Link from "next/link";
import type { ReactNode } from "react";

const ACCENT = {
  petrol: "text-accent-petrol",
  blue: "text-accent-blue",
  ochre: "text-accent-ochre",
} as const;

function Section({
  id,
  index,
  accent,
  title,
  visual,
  children,
}: {
  id: string;
  index: string;
  accent: keyof typeof ACCENT;
  title: ReactNode;
  visual?: ReactNode;
  children?: ReactNode;
}) {
  const heading = (
    <>
      <p className={`font-sans text-[10px] font-semibold tracking-[0.08em] md:text-xs ${ACCENT[accent]}`}>{index}</p>
      <h2
        id={`${id}-title`}
        className="mt-3 max-w-[760px] font-heading text-[1.9375rem] font-semibold leading-[1.22] text-primary md:mt-5 md:text-[42px] md:leading-[51px]"
      >
        {title}
      </h2>
    </>
  );

  return (
    <section id={id} className="border-t border-border py-16 md:py-[5.75rem]" aria-labelledby={`${id}-title`}>
      {visual ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,30.625rem)] lg:items-start lg:gap-16">
          <div>
            {heading}
            {children}
          </div>
          <div className="min-w-0">{visual}</div>
        </div>
      ) : (
        <>
          {heading}
          {children}
        </>
      )}
    </section>
  );
}

function Body({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`max-w-[640px] font-sans text-[15px] leading-[25px] text-secondary md:text-lg md:leading-[29px] ${className}`}>{children}</p>;
}

export function HowItWorksPage() {
  return (
    <article className="px-5 pb-16 pt-10 md:px-8 md:pb-24 md:pt-14">
      <header className="max-w-[820px]">
        <p className="font-sans text-[10px] font-semibold tracking-[0.16em] text-accent-petrol md:text-xs">
          TRANSPARENCIA EDITORIAL
        </p>
        <h1 className="mt-4 font-heading text-[2.5rem] font-semibold leading-[1.1] tracking-tight text-primary md:mt-6 md:text-5xl md:leading-[1.08] xl:text-[4.75rem] xl:leading-[82px]">
          Cómo funciona
          <span className="block">Sin Línea</span>
        </h1>
        <p className="mt-6 font-sans text-[17px] leading-[27px] text-secondary md:mt-8 md:text-[22px] md:leading-[34px]">
          Una noticia no empieza cuando una IA escribe un texto. Empieza cuando detectamos un suceso, buscamos evidencia
          y contrastamos lo que distintas fuentes sostienen.
        </p>
        <p className="mt-4 max-w-[760px] font-sans text-sm font-medium leading-[23px] text-primary md:mt-6 md:text-base md:leading-[26px]">
          Cada información importante puede rastrearse hasta las fuentes utilizadas para construirla.
        </p>
      </header>

      <PipelineStrip />

      <Section
        id="sucesos"
        index="01"
        accent="petrol"
        title={
          <>
            No pensamos en artículos.
            <span className="block">Pensamos en sucesos.</span>
          </>
        }
        visual={<EventMergeDiagram />}
      >
        <Body className="mt-4 md:mt-6">
          <span className="md:hidden">
            Si diez medios publican sobre el mismo hecho, Sin Línea reúne esas señales en un único suceso y construye una
            sola historia que puede evolucionar.
          </span>
          <span className="hidden md:inline">
            Si diez medios publican sobre el mismo hecho, Sin Línea no considera que existan diez noticias distintas.
            Reunimos las señales que describen el mismo suceso y construimos una sola historia que puede evolucionar.
          </span>
        </Body>
      </Section>

      <Section
        id="radar"
        index="02"
        accent="blue"
        title={
          <>
            Nuestro radar no rastrea
            <span className="block">Internet indiscriminadamente.</span>
          </>
        }
        visual={
          <div>
            <RadarDiagram />
            <p className="mt-4 hidden font-sans text-sm leading-[22px] text-secondary md:block">
              Una fuente encontrada durante una investigación no pasa automáticamente a formar parte del radar permanente.
            </p>
          </div>
        }
      >
        <Body className="mt-4 md:mt-6">
          <span className="md:hidden">
            Monitoreamos un conjunto de medios, organismos, gobiernos e instituciones. Una señal nueva activa la
            investigación; una fuente descubierta no entra automáticamente al radar permanente.
          </span>
          <span className="hidden md:inline">
            Sin Línea monitorea un conjunto de medios, organismos, instituciones y otras fuentes seleccionadas. Cuando
            una de ellas informa algo nuevo, eso funciona como una señal. Recién entonces comienza la investigación web.
          </span>
        </Body>
      </Section>

      <Section
        id="investigacion"
        index="03"
        accent="ochre"
        title={
          <>
            Investigamos antes
            <span className="block md:inline"> de escribir.</span>
          </>
        }
      >
        <Body className="mt-4 md:mt-5 md:max-w-[720px]">
          Una publicación activa la investigación. Buscamos fuentes que aporten información nueva, confirmen algo
          importante o permitan detectar contradicciones.
        </Body>
        <ResearchDiagram />
      </Section>

      <Section
        id="afirmaciones"
        index="04"
        accent="petrol"
        title={
          <>
            Separamos una noticia en
            <span className="block">afirmaciones comprobables.</span>
          </>
        }
      >
        <Body className="mt-4 md:mt-6">
          <span className="md:hidden">
            Antes de redactar identificamos las afirmaciones que realmente importan. Cada una puede conectarse con
            evidencia concreta.
          </span>
          <span className="hidden md:inline">
            Antes de redactar, identificamos las afirmaciones que realmente importan. Así podemos evaluar cada una por
            separado y conectarla con evidencia concreta.
          </span>
        </Body>
        <ClaimsDiagram />
      </Section>

      <Section
        id="estados"
        index="05"
        accent="blue"
        title={
          <>
            Mostramos el estado de
            <span className="block">la información.</span>
          </>
        }
      >
        <Body className="mt-4 md:hidden">
          El lector puede distinguir entre información respaldada, de una sola fuente, en disputa, contradicha o
          chequeada.
        </Body>
        <StatusGrid />
      </Section>

      <Section
        id="incertidumbre"
        index="06"
        accent="ochre"
        title={
          <>
            “No sabemos” también
            <span className="block">es información.</span>
          </>
        }
        visual={<UncertaintyDiagram />}
      >
        <p className="mt-4 max-w-[630px] font-sans text-[15px] font-medium leading-[25px] text-primary md:mt-8 md:text-lg md:leading-[29px]">
          Sin Línea no elige una versión solo para poder cerrar una historia.
        </p>
      </Section>

      <Section
        id="verificacion"
        index="07"
        accent="petrol"
        title={
          <>
            Verificamos cuando realmente
            <span className="block">puede cambiar la historia.</span>
          </>
        }
        visual={<VerificationList />}
      >
        <Body className="mt-4 md:mt-6 md:max-w-[650px]">
          Ponemos especial atención en declaraciones políticas, acusaciones, leyes, decretos, estadísticas, elecciones,
          cifras importantes, documentos públicos, responsabilidades y causalidad.
        </Body>
      </Section>

      <Section
        id="ia"
        index="08"
        accent="blue"
        title={
          <>
            La IA trabaja sobre evidencia,
            <span className="block">no al revés.</span>
          </>
        }
        visual={<AiStack />}
      >
        <Body className="mt-4 md:mt-6 md:max-w-[660px]">
          <span className="md:hidden">
            La IA interpreta publicaciones, compara información, detecta afirmaciones, encuentra inconsistencias y
            redacta. El artículo se construye a partir del estado estructurado del suceso.
          </span>
          <span className="hidden md:inline">
            Utilizamos inteligencia artificial para interpretar publicaciones, comparar información, detectar
            afirmaciones, encontrar inconsistencias y redactar. Pero el artículo final se construye a partir del estado
            estructurado del suceso.
          </span>
        </Body>
        <p className="mt-6 max-w-[700px] font-sans text-base font-semibold leading-6 text-accent-petrol md:mt-16 md:text-[22px] md:leading-[30px]">
          El artículo no es nuestra fuente de verdad.
        </p>
      </Section>

      <Section
        id="auditoria"
        index="09"
        accent="ochre"
        title="Escribir no es el último paso."
        visual={<AuditList />}
      >
        <Body className="mt-4 md:mt-5 md:max-w-[690px]">
          <span className="md:hidden">
            El borrador pasa por una auditoría que revisa nombres, cifras, fechas, atribuciones, contradicciones,
            afirmaciones sin respaldo y lenguaje editorial.
          </span>
          <span className="hidden md:inline">
            Antes de publicar, el borrador pasa por una auditoría que revisa nombres, cifras, fechas, atribuciones,
            contradicciones, afirmaciones sin respaldo y lenguaje editorial.
          </span>
        </Body>
      </Section>

      <Section
        id="historial"
        index="10"
        accent="petrol"
        title={
          <>
            Un suceso continúa
            <span className="block">después de publicado.</span>
          </>
        }
        visual={<EventTimeline />}
      >
        <Body className="mt-4 md:mt-6">
          <span className="md:hidden">
            El mismo suceso se actualiza cuando aparece información materialmente nueva y conserva su historial.
          </span>
          <span className="hidden md:inline">
            Sin Línea no necesita publicar una URL nueva cada vez que aparece información material. El mismo suceso se
            actualiza y conserva su historial.
          </span>
        </Body>
      </Section>

      <Section
        id="fuentes"
        index="11"
        accent="blue"
        title={
          <>
            Podés ver de dónde sale
            <span className="block">la información.</span>
          </>
        }
      >
        <Body className="mt-4 md:hidden">
          Cada noticia muestra las fuentes utilizadas y, cuando corresponde, el estado de afirmaciones importantes.
        </Body>
        <div className="mt-8 md:mt-10">
          <ArticleEvidenceDemo />
        </div>
      </Section>

      <section className="border-t border-border py-16 md:py-[5.75rem]" aria-labelledby="principios-title">
        <p id="principios-title" className="font-sans text-[10px] font-semibold tracking-[0.08em] text-accent-petrol md:text-xs">
          NUESTROS PRINCIPIOS
        </p>
        <Principles />
        <p className="mt-6 max-w-[900px] font-sans text-[15px] leading-6 text-secondary md:mt-8 md:text-base md:leading-[27px]">
          <span className="md:hidden">
            No clasificamos los hechos como positivos o negativos. No usamos orientación política como señal de ranking.
            No convertimos declaraciones en hechos. No ocultamos las fuentes. No fabricamos certeza cuando la evidencia
            no existe.
          </span>
          <span className="hidden md:inline">
            No clasificamos los hechos como positivos o negativos. No utilizamos orientación política como señal de
            ranking. No convertimos declaraciones en hechos. No ocultamos las fuentes. No fabricamos certeza cuando la
            evidencia no existe.
          </span>
        </p>
      </section>

      <section className="rounded-2xl border border-border bg-surface px-4 py-6 md:flex md:items-end md:justify-between md:px-7 md:py-8">
        <div>
          <p className="max-w-[780px] font-heading text-[22px] font-semibold leading-7 text-primary md:text-[28px] md:leading-[35px]">
            Ahora podés ver cómo aplicamos estos principios.
          </p>
          <Link
            href="/"
            className="mt-6 inline-block font-sans text-[15px] font-semibold text-accent-petrol hover:text-accent-blue md:mt-10"
          >
            Ver las noticias →
          </Link>
        </div>
        <p className="mt-6 font-sans text-xs leading-[18px] text-secondary md:mt-0 md:text-right">
          <span className="md:hidden">Sin Línea · Transparencia · Correcciones</span>
          <span className="hidden md:inline">Sin Línea · Transparencia · Fuentes · Correcciones</span>
        </p>
      </section>
    </article>
  );
}
