/** Titre de section éditorial (DESIGN.md § 4) : filet encre, numéro « N° 01 », titre serif. */
import type { ReactNode } from "react";

interface SectionHeadingProps {
  id: string;
  number?: string;
  title: string;
  action?: ReactNode;
}

export function SectionHeading({ id, number, title, action }: SectionHeadingProps) {
  return (
    <div className="flex flex-wrap items-baseline gap-4 border-t border-ink pt-4">
      {number && <span className="font-display text-ui text-ink-2">{number}</span>}
      <h2 id={id} className="font-display text-h2 font-semibold">
        {title}
      </h2>
      {action && <div className="ml-auto">{action}</div>}
    </div>
  );
}
