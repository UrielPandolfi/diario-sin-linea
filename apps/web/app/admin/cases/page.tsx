"use client";

import { adminJson } from "@/lib/admin";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type CaseRow = {
  id: string;
  public_code: string;
  status: string;
  reason: string;
  outcome: string | null;
  created_at: string | null;
  article_slug: string | null;
  headline: string | null;
};

const STATUS_OPTIONS = ["", "RECEIVED", "REVIEWING", "RESOLVED"];
const REASON_OPTIONS = [
  "",
  "INCORRECT_FACT",
  "MISSING_INFO",
  "SOURCE_MISREAD",
  "CONTRIBUTE_INFO",
  "INVOLVED_RESPONSE",
  "WHY_WRITTEN",
  "WHY_PUBLISHED",
  "OTHER",
];

export default function AdminCasesPage() {
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (reason) params.set("reason", reason);
    const query = params.toString();
    setRows(await adminJson<CaseRow[]>(`/api/v1/admin/cases${query ? `?${query}` : ""}`));
  }, [status, reason]);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los casos.");
    });
  }, [load]);

  return (
    <main className="space-y-6">
      <div>
        <p className="font-heading text-sm font-medium uppercase tracking-[0.18em] text-accent-ochre">Casos</p>
        <h1 className="mt-2 font-heading text-3xl font-medium text-primary">Reportes y consultas</h1>
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="font-sans text-sm text-secondary">
          Estado
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="ml-2 border border-border bg-background px-2 py-1 text-primary"
          >
            {STATUS_OPTIONS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "Todos"}
              </option>
            ))}
          </select>
        </label>
        <label className="font-sans text-sm text-secondary">
          Motivo
          <select
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="ml-2 border border-border bg-background px-2 py-1 text-primary"
          >
            {REASON_OPTIONS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "Todos"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p className="font-sans text-sm text-accent-ochre">{error}</p> : null}
      {rows.length === 0 ? (
        <p className="font-sans text-sm text-secondary">No hay casos con esos filtros.</p>
      ) : (
        <ul className="divide-y divide-border border border-border">
          {rows.map((row) => (
            <li key={row.id} className="px-4 py-3">
              <Link href={`/admin/cases/${row.id}`} className="font-sans text-sm text-primary">
                {row.public_code} · {row.status} · {row.reason}
              </Link>
              <p className="mt-1 font-sans text-xs text-secondary">
                {row.headline ?? "Consulta general"}
                {row.article_slug ? ` · ${row.article_slug}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}