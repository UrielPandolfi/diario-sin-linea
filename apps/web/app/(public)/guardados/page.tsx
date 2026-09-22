import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Guardados",
  robots: { index: false, follow: false },
};

export default function SavedPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <UpcomingFeature title="Guardados" description="Volvé a los sucesos que quieras retomar más tarde." />
    </div>
  );
}
