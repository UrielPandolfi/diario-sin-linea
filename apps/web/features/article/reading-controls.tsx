"use client";

import { READING_SIZE_KEY, READING_SIZES, resolveReadingSize, type ReadingSize } from "./reading";
import { useEffect, useState } from "react";

export function useReadingSize(): [ReadingSize, (next: ReadingSize) => void] {
  const [size, setSize] = useState<ReadingSize>("md");

  useEffect(() => {
    try {
      setSize(resolveReadingSize(localStorage.getItem(READING_SIZE_KEY)));
    } catch {
      setSize("md");
    }
  }, []);

  function update(next: ReadingSize) {
    setSize(next);
    try {
      localStorage.setItem(READING_SIZE_KEY, next);
    } catch {
      /* private mode */
    }
  }

  return [size, update];
}

export function ReadingSizeToggle({
  value,
  onChange,
}: {
  value: ReadingSize;
  onChange: (next: ReadingSize) => void;
}) {
  return (
    <div role="group" aria-label="Tamaño del texto" className="flex items-end gap-0.5">
      {READING_SIZES.map((size) => {
        const selected = value === size;
        const label = size === "sm" ? "Texto chico" : size === "md" ? "Texto mediano" : "Texto grande";
        const typeClass = size === "sm" ? "text-[13px]" : size === "md" ? "text-[15px]" : "text-[17px]";
        return (
          <button
            key={size}
            type="button"
            aria-pressed={selected}
            aria-label={label}
            onClick={() => onChange(size)}
            className={`inline-flex h-11 w-8 items-end justify-center pb-2 font-heading leading-none transition-colors ${typeClass} ${
              selected ? "font-semibold text-primary" : "text-secondary hover:text-primary"
            }`}
          >
            A
          </button>
        );
      })}
    </div>
  );
}
