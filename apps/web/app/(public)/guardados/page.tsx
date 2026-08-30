import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Guardados",
};

export default function SavedPage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border">
      <UpcomingFeature title="Guardados" description="Volvé a los sucesos que quieras retomar más tarde." />
    </div>
  );
}
