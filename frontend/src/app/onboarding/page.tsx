import type { Metadata } from "next";

import { OnboardingPicker } from "./onboarding-picker";

export const metadata: Metadata = { title: "Tes goûts" };

export default function Page() {
  return <OnboardingPicker />;
}
