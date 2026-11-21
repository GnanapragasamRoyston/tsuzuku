import type { Metadata } from "next";

import { MyList } from "./my-list";

export const metadata: Metadata = { title: "Ma liste" };

export default function Page() {
  return <MyList />;
}
