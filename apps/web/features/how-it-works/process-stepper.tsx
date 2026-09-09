"use client";

import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type ProcessStep = {
  id: string;
  index: string;
  label: string;
  title: string;
  body: string;
  note?: string;
  visual: ReactNode;
};

export function ProcessStepper({ steps }: { steps: ProcessStep[] }) {
  const [active, setActive] = useState(0);
  const tabsRef = useRef<Array<HTMLButtonElement | null>>([]);

  const focusTab = (index: number) => {
    const next = (index + steps.length) % steps.length;
    setActive(next);
    tabsRef.current[next]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      focusTab(active + 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      focusTab(active - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTab(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusTab(steps.length - 1);
    }
  };

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] lg:gap-14">
      <div
        role="tablist"
        aria-label="Etapas del proceso"
        aria-orientation="vertical"
        className="-mx-5 flex snap-x gap-2 overflow-x-auto px-5 pb-1 lg:mx-0 lg:flex-col lg:gap-0 lg:overflow-visible lg:border-l lg:border-border lg:px-0 lg:pb-0"
      >
        {steps.map((step, index) => {
          const selected = index === active;
          return (
            <button
              key={step.id}
              ref={(node) => {
                tabsRef.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`tab-${step.id}`}
              aria-selected={selected}
              aria-controls={`panel-${step.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(index)}
              onKeyDown={onKeyDown}
              className={`shrink-0 snap-start border px-4 py-3 text-left font-sans transition-colors lg:w-full lg:border-0 lg:border-l-2 lg:px-5 lg:py-4 ${
                selected
                  ? "border-accent-petrol text-primary lg:-ml-px lg:border-l-accent-petrol lg:bg-surface"
                  : "border-border text-secondary hover:text-primary lg:-ml-px lg:border-l-transparent lg:hover:bg-surface/60"
              }`}
            >
              <span
                className={`font-sans text-[10px] font-semibold tracking-[0.1em] ${
                  selected ? "text-accent-petrol" : "text-secondary"
                }`}
              >
                {step.index}
              </span>
              <span className="ml-2.5 font-sans text-[11px] font-semibold tracking-[0.08em] lg:ml-3 lg:text-xs">
                {step.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* La altura mínima evita que el bloque salte al cambiar de etapa. */}
      <div className="min-w-0 lg:min-h-[34rem]">
        {steps.map((step, index) => (
          <div
            key={step.id}
            role="tabpanel"
            id={`panel-${step.id}`}
            aria-labelledby={`tab-${step.id}`}
            hidden={index !== active}
            tabIndex={0}
            className="sl-panel focus-visible:outline-none"
          >
            <h3 className="max-w-[620px] font-heading text-[1.625rem] font-semibold leading-[1.2] text-primary md:text-[2.125rem]">
              {step.title}
            </h3>
            <p className="mt-4 max-w-[600px] font-sans text-[15px] leading-[25px] text-secondary md:mt-5 md:text-[17px] md:leading-[28px]">
              {step.body}
            </p>
            {step.note ? (
              <p className="mt-4 max-w-[600px] font-sans text-sm font-medium leading-[23px] text-accent-petrol">
                {step.note}
              </p>
            ) : null}
            <div className="mt-8 md:mt-10">{step.visual}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
