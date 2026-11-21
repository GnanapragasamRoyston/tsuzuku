# Tsuzuku — front

Next.js 16 (App Router, TypeScript), Tailwind v4, TanStack Query. Tout travail ici respecte
[`docs/DESIGN.md`](../docs/DESIGN.md) ; les choix techniques sont dans
[ADR 009](../docs/decisions/009-front-next.md).

```bash
npm run dev        # http://localhost:3000 (l'API doit tourner : make api)
npm run lint && npm run typecheck && npm test   # Vitest, garde-fous du design compris
npm run e2e        # Playwright : base de test, vraie API (port 8001), build de prod (port 3001)
```

- `src/app/` : pages (accueil rendu côté serveur ; pages de compte côté navigateur).
- `src/components/` : composants signature de DESIGN.md (`ui/` : bouton, champ, onglets).
- `src/lib/` : logique testée (progression, erreurs, formats, client API).
- `src/proxy.ts` : renvoi optimiste vers la connexion (l'API reste seule juge de la session).
- Variable d'environnement côté serveur : `API_URL` (défaut `http://127.0.0.1:8000`).
