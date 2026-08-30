import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Seguidos",
};

export default function FollowingPage() {
  return (
    <div className="mx-auto min-h-screen max-w-2xl border-x border-border">
      <UpcomingFeature
        title="Seguidos"
        description="Seguí temas, lugares y protagonistas para encontrarlos más rápido."
      />
    </div>
  );
}
