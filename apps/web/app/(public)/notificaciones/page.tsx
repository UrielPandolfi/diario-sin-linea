import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Notificaciones",
  robots: { index: false, follow: false },
};

export default function NotificationsPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <UpcomingFeature
        title="Notificaciones"
        description="Recibí avisos cuando cambie algo importante."
      />
    </div>
  );
}
