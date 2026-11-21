import { ButtonLink } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-prose flex-col items-start gap-6 px-5 py-24">
      <h1 className="font-display text-h1 font-bold">Page introuvable</h1>
      <p className="text-ink-2">Ce lien ne mène nulle part. Il a peut-être changé.</p>
      <ButtonLink href="/">Retour à l&apos;accueil</ButtonLink>
    </div>
  );
}
