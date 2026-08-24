import { ThemeToggle } from "@/components/theme-toggle";

export const dynamic = "force-dynamic";

type HealthPayload = {
  status?: string;
  postgres?: string;
  redis?: string;
};

async function loadHealth(): Promise<{ ok: boolean; status: number; data: HealthPayload | { error: string } }> {
  const base = process.env.API_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${base}/health`, { cache: "no-store" });
    const data = (await response.json()) as HealthPayload;
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      data: { error: error instanceof Error ? error.message : "Error desconocido" },
    };
  }
}

export default async function HomePage() {
  const health = await loadHealth();
  const payload = health.data;

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-8 px-6">
      <div className="flex justify-end">
        <ThemeToggle />
      </div>

      <div className="space-y-3">
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">
          Sin Línea
        </p>
        <h1 className="font-heading text-3xl font-medium leading-tight text-primary">
          El suceso es la unidad.
        </h1>
        <p className="font-sans text-secondary">
          Foundation lista. El frontend consulta el backend real; no hay datos de demostración.
        </p>
      </div>

      <section className="border border-border bg-surface p-5">
        <p className="mb-3 font-sans text-sm text-accent-blue">Estado de la API</p>
        <dl className="grid grid-cols-2 gap-2 font-sans text-sm text-primary">
          <dt className="text-secondary">HTTP</dt>
          <dd>{health.ok ? health.status : health.status || "sin respuesta"}</dd>
          {"postgres" in payload ? (
            <>
              <dt className="text-secondary">Postgres</dt>
              <dd>{payload.postgres}</dd>
              <dt className="text-secondary">Redis</dt>
              <dd>{payload.redis}</dd>
              <dt className="text-secondary">Servicio</dt>
              <dd>{payload.status}</dd>
            </>
          ) : (
            <>
              <dt className="text-secondary">Error</dt>
              <dd className="text-accent-ochre">{"error" in payload ? payload.error : "falló la consulta"}</dd>
            </>
          )}
        </dl>
      </section>
    </main>
  );
}
