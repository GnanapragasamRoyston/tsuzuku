/**
 * Boutons (DESIGN.md § 5.7). Une seule variante « primary » (corail) par écran : c'est le budget
 * du corail (§ 1.3). Hauteur minimale 44 px (cible tactile). Pas d'agrandissement au survol.
 */
import clsx from "clsx";
import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps } from "react";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "destructive";

const BASE =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md text-ui font-semibold " +
  "transition-colors duration-150 ease-out disabled:cursor-not-allowed aria-disabled:cursor-not-allowed";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent px-6 text-on-accent hover:bg-accent-hover disabled:bg-raised disabled:text-disabled",
  secondary:
    "border border-line-strong px-4 text-ink hover:bg-hover disabled:border-disabled disabled:text-disabled",
  quiet:
    "px-1 text-ink underline decoration-1 underline-offset-4 hover:decoration-2 disabled:text-disabled",
  destructive: "border border-accent px-4 text-accent hover:bg-hover disabled:text-disabled",
};

export function buttonClass(variant: ButtonVariant = "secondary", extra?: string): string {
  return clsx(BASE, VARIANTS[variant], extra);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Chargement : libellé « Un instant… », largeur figée par le contenu, aria-busy. */
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  loading = false,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClass(variant, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? "Un instant…" : children}
    </button>
  );
}

type ButtonLinkProps = ComponentProps<typeof Link> & { variant?: ButtonVariant };

export function ButtonLink({ variant = "secondary", className, ...props }: ButtonLinkProps) {
  return <Link className={buttonClass(variant, className)} {...props} />;
}
