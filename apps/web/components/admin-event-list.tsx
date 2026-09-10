import Link from "next/link";
import {
  formatTokens,
  formatWhen,
  labelLookup,
  PIPELINE_STAGE_LABELS,
  PIPELINE_STATUS_LABELS,
  EVENT_STATUS_LABELS,
  type AdminEvent,
} from "@/lib/admin";

type AdminEventListProps = {
  events: AdminEvent[];
  empty: string;
};

export function AdminEventList({ events, empty }: AdminEventListProps) {
  if (events.length === 0) {
    return <p className="px-4 py-6 font-sans text-sm text-secondary">{empty}</p>;
  }

  return (
    <ul className="divide-y divide-border">
      {events.map((event) => (
        <li key={event.id}>
          <Link href={`/admin/events/${event.id}`} className="block px-4 py-3 hover:bg-hover">
            <p className="font-sans text-primary">{event.title_internal}</p>
            <p className="mt-1 font-sans text-xs text-secondary">
              {event.event_type} · {labelLookup(EVENT_STATUS_LABELS, event.status)}
              {event.pipeline_stage
                ? ` · ${labelLookup(PIPELINE_STAGE_LABELS, event.pipeline_stage)}${
                    event.pipeline_run_status
                      ? ` · ${labelLookup(PIPELINE_STATUS_LABELS, event.pipeline_run_status)}`
                      : ""
                  }`
                : ""}
              {typeof event.tokens_total === "number"
                ? ` · ${formatTokens(event.tokens_total)} tok`
                : ""}
              {event.locality ? ` · ${event.locality}` : ""}
              {event.province ? `, ${event.province}` : ""} · {formatWhen(event.detected_at)}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
