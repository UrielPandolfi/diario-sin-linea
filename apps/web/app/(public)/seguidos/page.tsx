import { UpcomingFeature } from "@/features/upcoming/upcoming-feature";

export const metadata = {
  title: "Seguidos",
  robots: { index: false, follow: false },
};

export default function FollowingPage() {
  return (
    <div className="mx-auto min-h-screen max-w-measure">
      <UpcomingFeature
        title="Seguidos"
        description="Seguí temas, lugares y protagonistas para encontrarlos más rápido."
      />
    </div>
  );
}
