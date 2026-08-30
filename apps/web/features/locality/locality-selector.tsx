"use client";

import { fetchLocalities } from "@/lib/api/public";
import { writeLocalityCookie } from "@/lib/locality";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function LocalitySelector({
  current,
  onSaved,
}: {
  current: string;
  onSaved?: (value: string) => void;
}) {
  const router = useRouter();
  const [options, setOptions] = useState<string[]>([]);
  const [value, setValue] = useState(current);
  const [custom, setCustom] = useState("");

  useEffect(() => {
    void fetchLocalities()
      .then((payload) => setOptions(payload.items))
      .catch(() => setOptions([]));
  }, []);

  useEffect(() => {
    setValue(current);
  }, [current]);

  function apply(next: string) {
    const locality = next.trim();
    if (!locality) return;
    writeLocalityCookie(locality);
    onSaved?.(locality);
    router.refresh();
  }

  const known = options.includes(value);

  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="block min-w-[12rem] flex-1 font-sans text-sm text-secondary">
        Localidad
        {options.length > 0 ? (
          <select
            value={known ? value : ""}
            onChange={(event) => {
              setValue(event.target.value);
              apply(event.target.value);
            }}
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
          >
            {!known && value ? <option value={value}>{value}</option> : null}
            {!known ? <option value="">Elegí una localidad</option> : null}
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={custom || value}
            onChange={(event) => setCustom(event.target.value)}
            onBlur={() => apply(custom || value)}
            placeholder="Rosario"
            className="mt-1 w-full border border-border bg-background px-3 py-2 font-sans text-primary"
          />
        )}
      </label>
    </div>
  );
}
