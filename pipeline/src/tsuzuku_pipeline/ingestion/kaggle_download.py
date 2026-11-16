"""Téléchargement idempotent des CSV du dataset Kaggle.

Identifiants : jeton dans ~/.kaggle/access_token (ou variable KAGGLE_API_TOKEN). Le jeton n'est
jamais lu ni loggé ici : c'est la bibliothèque kaggle qui le charge.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUTH_HELP = (
    "Authentification Kaggle impossible. Place ton jeton dans ~/.kaggle/access_token "
    "(chmod 600) ou dans la variable KAGGLE_API_TOKEN. Vérifie aussi la connexion réseau."
)


class DownloadError(Exception):
    """Téléchargement impossible ou fichier incohérent."""


def _default_api() -> Any:
    # Import paresseux : le paquet kaggle s'authentifie dès l'import, ce qui ne doit pas arriver
    # quand on importe simplement ce module (tests, autres étapes du pipeline).
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi

        api = KaggleApi()
        api.authenticate()
    except Exception as exc:
        # `from None` : le message d'origine peut contenir le jeton, on ne le propage pas.
        logger.error("Échec d'authentification Kaggle (%s)", type(exc).__name__)
        raise DownloadError(AUTH_HELP) from None
    return api


def _remote_sizes(api: Any, dataset: str, wanted: set[str]) -> dict[str, int]:
    """Taille attendue de chaque fichier voulu, en parcourant la liste paginée du dataset.

    On s'arrête dès que tout est trouvé : le dataset liste aussi ~17 500 zips html inutiles.
    """
    sizes: dict[str, int] = {}
    token = None
    try:
        while True:
            page = api.dataset_list_files(dataset, page_token=token, page_size=200)
            for f in page.files:
                if f.name in wanted:
                    sizes[f.name] = int(f.total_bytes)
            token = page.next_page_token
            if not token or wanted <= sizes.keys():
                break
    except Exception as exc:
        # On ne connaît pas la cause exacte (401, 404, réseau...) sans lire le message d'origine,
        # qui peut contenir le jeton : on donne le type d'erreur et toutes les pistes.
        kind = type(exc).__name__
        logger.error("Échec de l'appel à l'API Kaggle (%s)", kind)
        raise DownloadError(
            f"Appel à l'API Kaggle impossible pour {dataset} ({kind}). Vérifie le slug "
            f"data.kaggle_dataset dans settings.yaml, la connexion réseau, et le jeton "
            f"(~/.kaggle/access_token ou KAGGLE_API_TOKEN)."
        ) from None

    missing = sorted(wanted - sizes.keys())
    if missing:
        raise DownloadError(f"Fichiers absents du dataset {dataset} : {', '.join(missing)}")
    return sizes


def _sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    # Lecture par blocs de 1 Mo : animelist.csv fait ~2 Go, on ne le charge pas en mémoire.
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download_dataset(
    dataset: str,
    files: list[str],
    raw_dir: Path,
    api: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    """Télécharge `files` dans `raw_dir` et écrit manifest.json (taille + sha256).

    Idempotent, en deux niveaux :
    1. si manifest.json couvre tous les fichiers et que leurs tailles sur disque correspondent,
       on s'arrête là, sans réseau ni jeton : `make data` marche hors ligne une fois les données
       présentes ;
    2. sinon on demande les tailles à l'API et on ne télécharge que les fichiers absents ou
       incomplets. Le sha256 n'est recalculé que pour les fichiers (re)téléchargés : on ne relit
       pas 2 Go à chaque lancement. Il sert à la traçabilité (sur quels octets on a calculé).
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_manifest(raw_dir, dataset)

    if not force and _manifest_matches_disk(previous, files, raw_dir):
        logger.info("Fichiers bruts déjà présents et conformes au manifeste : rien à télécharger")
        return {"dataset": dataset, "files": {n: previous[n] for n in files}}

    api = api or _default_api()
    sizes = _remote_sizes(api, dataset, set(files))

    entries: dict[str, dict[str, Any]] = {}
    for name in files:
        target = raw_dir / name
        expected = sizes[name]
        up_to_date = target.is_file() and target.stat().st_size == expected
        if force or not up_to_date:
            logger.info("Téléchargement de %s (%.1f Mo)", name, expected / 1e6)
            if target.is_file() and not force:
                # Fichier incomplet : on le retire, sinon la bibliothèque le croirait à jour.
                # force=False lui laisse reprendre son .kaggle-partial au lieu de repartir de zéro.
                target.unlink()
            # unzip=True : Kaggle compresse les gros fichiers à la volée, on veut le CSV brut.
            api.dataset_download_file(
                dataset, name, path=raw_dir, force=force, quiet=False, unzip=True
            )
        else:
            logger.info("%s déjà présent, ignoré", name)

        actual = target.stat().st_size if target.is_file() else -1
        if actual != expected:
            raise DownloadError(
                f"{name} : taille {actual} octets, {expected} attendus (téléchargement corrompu ?)"
            )
        known = previous.get(name)
        reuse = up_to_date and not force and known and known["size"] == expected
        entries[name] = {"size": expected, "sha256": known["sha256"] if reuse else _sha256(target)}

    manifest = {"dataset": dataset, "files": entries}
    (raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _load_manifest(raw_dir: Path, dataset: str) -> dict[str, dict[str, Any]]:
    """Entrées du manifeste précédent, ou {} s'il est absent, illisible ou d'un autre dataset."""
    path = raw_dir / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("dataset") != dataset:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def _manifest_matches_disk(previous: dict[str, Any], files: list[str], raw_dir: Path) -> bool:
    for name in files:
        entry, target = previous.get(name), raw_dir / name
        if not entry or not target.is_file() or target.stat().st_size != entry.get("size"):
            return False
    return True
