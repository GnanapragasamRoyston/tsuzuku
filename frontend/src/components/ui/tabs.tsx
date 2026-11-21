/**
 * Onglets (DESIGN.md § 5.6), sur Radix Tabs : rôles tablist/tab/tabpanel et flèches du clavier
 * fournis. Actif : encre + trait corail de 2 px dessous (signal « élément actif », § 1.3).
 */
"use client";

import * as RadixTabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import type { ComponentProps } from "react";

export const Tabs = RadixTabs.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof RadixTabs.List>) {
  return (
    <RadixTabs.List
      // Défilement horizontal sur mobile, sans barre visible (DESIGN.md § 5.6).
      className={clsx(
        "flex gap-2 overflow-x-auto overflow-y-hidden border-b border-line [scrollbar-width:none]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  onFocus,
  ...props
}: ComponentProps<typeof RadixTabs.Trigger>) {
  return (
    <RadixTabs.Trigger
      // Onglet ramené dans la vue quand il reçoit le focus (clic ou flèches) : sur mobile, la
      // liste défile horizontalement (DESIGN.md § 5.6).
      onFocus={(event) => {
        event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
        onFocus?.(event);
      }}
      className={clsx(
        "-mb-px min-h-11 shrink-0 border-b-2 border-transparent px-3 text-ui font-semibold",
        "text-ink-2 tabular-nums transition-colors duration-150 ease-out hover:text-ink",
        "data-[state=active]:border-accent data-[state=active]:text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof RadixTabs.Content>) {
  return <RadixTabs.Content className={className} {...props} />;
}
