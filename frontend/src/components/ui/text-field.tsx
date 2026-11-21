/**
 * Champ de formulaire (DESIGN.md § 5.8) : libellé au-dessus, aide et erreur reliées par
 * aria-describedby, erreur annoncée « Erreur : » aux lecteurs d'écran.
 */
"use client";

import clsx from "clsx";
import { type InputHTMLAttributes, useId } from "react";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: string;
  error?: string | null;
}

export const INPUT_CLASS =
  "min-h-11 w-full rounded-md border border-line-strong bg-surface px-3 text-body text-ink " +
  "transition-colors duration-150 ease-out placeholder:text-ink-2 hover:border-ink-2 " +
  "aria-invalid:border-accent disabled:border-disabled disabled:text-disabled";

export function TextField({ label, help, error, id, className, ...props }: TextFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const helpId = `${inputId}-aide`;
  const errorId = `${inputId}-erreur`;
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className={clsx("flex flex-col gap-2", className)}>
      <label htmlFor={inputId} className="text-small font-semibold text-ink-2">
        {label}
      </label>
      <input
        id={inputId}
        className={INPUT_CLASS}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...props}
      />
      {help && (
        <p id={helpId} className="text-small text-ink-2">
          {help}
        </p>
      )}
      {error && (
        // role="alert" : l'erreur est lue dès qu'elle apparaît (ex. mot de passe incorrect).
        <p id={errorId} role="alert" className="text-small text-accent">
          <span className="sr-only">Erreur : </span>
          {error}
        </p>
      )}
    </div>
  );
}
