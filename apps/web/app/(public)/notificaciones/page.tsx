import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Notificaciones",
};

export default function NotificationsPage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border">
      <UpcomingFeature
        title="Notificaciones"
        description="Recibí avisos cuando cambie algo importante."
      />
    </div>
  );
}
