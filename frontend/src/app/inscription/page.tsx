import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Inscription" };

export default function Page() {
  // Suspense : le formulaire lit ?suivant= (useSearchParams), connu seulement à la requête.
  return (
    <Suspense>
      <AuthForm mode="register" />
    </Suspense>
  );
}
