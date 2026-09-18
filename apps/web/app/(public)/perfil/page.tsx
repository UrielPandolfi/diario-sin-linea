import { ProfileView } from "@/features/profile/profile-view";

export const metadata = {
  title: "Perfil",
  robots: { index: false, follow: false },
};

export default function ProfilePage() {
  return <ProfileView />;
}
