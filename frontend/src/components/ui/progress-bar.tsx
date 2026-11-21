/**
 * Barre de progression (DESIGN.md § 5.2) : 4 px, rayon sm. Décorative (aria-hidden) : la
 * progression est toujours écrite en texte à côté (« 7 / 24 ép. »).
 * Animée par transform (scaleX), jamais par width (§ 6).
 */
import clsx from "clsx";

export function ProgressBar({ share, muted = false }: { share: number | null; muted?: boolean }) {
  return (
    <div aria-hidden="true" className="h-1 w-full overflow-hidden rounded-sm bg-line">
      <div
        className={clsx(
          "h-1 w-full origin-left rounded-sm transition-transform duration-200 ease-out",
          muted ? "bg-line-strong" : "bg-ink-2",
        )}
        style={{ transform: `scaleX(${share ?? 0})` }}
      />
    </div>
  );
}
