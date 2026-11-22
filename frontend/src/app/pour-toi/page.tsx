import type { Metadata } from "next";

import { ForYouPage } from "./for-you";

export const metadata: Metadata = { title: "Pour toi" };

export default function Page() {
  return <ForYouPage />;
}
