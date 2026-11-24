/**
 * Invitation à installer l'appli (DESIGN.md § 5.10, SPEC § 8.1) : en haut de « Ma liste », jamais
 * à la première visite (après l'onboarding ou un premier ajout), jamais une fois installée.
 * Android / ordinateur : invite du navigateur (beforeinstallprompt) ; iPhone : mini-guide.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DISMISSED_KEY,
  USEFUL_ACTION_KEY,
  detectPlatform,
  type InstallPlatform,
  shouldOfferInstall,
} from "@/lib/install";

interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
}

export function markUsefulAction(): void {
  try {
    window.localStorage.setItem(USEFUL_ACTION_KEY, "1");
  } catch {
    // Stockage plein ou bloqué : l'invitation n'apparaîtra pas, l'ajout, lui, a réussi.
  }
}

// 1. Chrome n'émet beforeinstallprompt qu'une fois par chargement, souvent avant que « Ma liste »
// soit affichée (onboarding puis navigation interne) : capté dès le chargement du module, gardé.
let capturedPrompt: Event | null = null;
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // pas de bannière du navigateur : c'est nous qui proposons
    capturedPrompt = event;
  });
}

export function InstallInvite() {
  const [platform, setPlatform] = useState<InstallPlatform | null>(null);
  const [promptEvent, setPromptEvent] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true;
    const dismissed = Number(window.localStorage.getItem(DISMISSED_KEY)) || null;
    const offer = shouldOfferInstall({
      standalone,
      usefulAction: window.localStorage.getItem(USEFUL_ACTION_KEY) === "1",
      dismissedAt: dismissed,
      now: Date.now(),
    });
    if (!offer) return;
    const detected = detectPlatform(navigator.userAgent, navigator.maxTouchPoints);
    // Lecture de l'environnement du navigateur au montage (rien côté serveur).
    if (detected === "ios") setPlatform("ios"); // eslint-disable-line react-hooks/set-state-in-effect
    if (capturedPrompt) {
      setPromptEvent(capturedPrompt as InstallPromptEvent);  
      setPlatform("prompt");
    }
    const onPrompt = (event: Event) => {
      event.preventDefault(); // pas de bannière du navigateur : c'est nous qui proposons
      setPromptEvent(event as InstallPromptEvent);
      setPlatform("prompt");
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (!platform || (platform === "prompt" && !promptEvent)) return null;
  const later = () => {
    window.localStorage.setItem(DISMISSED_KEY, String(Date.now()));
    setPlatform(null);
  };
  return (
    <aside aria-labelledby="installer" className="flex flex-col gap-3 rounded-lg bg-surface p-5">
      <h2 id="installer" className="text-ui font-semibold">
        Installer Tsuzuku
      </h2>
      <p className="text-ink-2">
        Garde Tsuzuku sur ton écran d&apos;accueil : il s&apos;ouvre comme une appli, même sans
        réseau.
      </p>
      {platform === "ios" ? (
        <ol className="flex list-decimal flex-col gap-1 pl-5">
          <li>Touche Partager (le carré avec une flèche).</li>
          <li>Puis « Sur l&apos;écran d&apos;accueil ».</li>
        </ol>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {platform === "prompt" && promptEvent && (
          <Button
            onClick={async () => {
              await promptEvent.prompt();
              setPlatform(null);
            }}
          >
            Installer l&apos;appli
          </Button>
        )}
        <Button variant="quiet" onClick={later}>
          Plus tard
        </Button>
        <Link href="/installer" className="text-small text-ink-2 underline">
          Tout savoir
        </Link>
      </div>
    </aside>
  );
}
