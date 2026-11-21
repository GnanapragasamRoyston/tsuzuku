import type { Metadata } from "next";

import { Account } from "./account";

export const metadata: Metadata = { title: "Ton compte" };

export default function Page() {
  return <Account />;
}
