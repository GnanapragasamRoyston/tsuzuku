"""Mécanique d'étapes partagée par `make data` et `make spark`.

Idempotence « à la make » : une étape est sautée si
1. ses sorties sont complètes ET plus récentes que ses entrées ;
2. et, si elle dépend de réglages, le tampon de config enregistré au dernier succès est identique
   à la config actuelle. Changer un seuil dans settings.yaml rend donc l'étape périmée.
Le tampon n'est écrit qu'APRÈS un build réussi : une étape qui échoue (ex. contrôle de cohérence)
sera refaite au prochain run, même si elle a eu le temps d'écrire ses fichiers.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger("tsuzuku_pipeline.steps")


def marker(path: Path) -> Path:
    # Pour un dossier Parquet, _SUCCESS est écrit par Spark en toute fin d'écriture : son absence
    # signale une sortie partielle (job interrompu). Pour un fichier, c'est le fichier lui-même.
    return path / "_SUCCESS" if path.suffix == "" else path


def is_fresh(outputs: Iterable[Path], inputs: Iterable[Path]) -> bool:
    markers = [marker(p) for p in outputs]
    # Sans sortie fichier (ex. chargement en base), rien ne prouve que l'étape est à jour.
    if not markers or not all(m.is_file() for m in markers):
        return False
    sources = [marker(p) for p in inputs if marker(p).is_file()]
    if not sources:
        return True
    return min(m.stat().st_mtime_ns for m in markers) >= max(s.stat().st_mtime_ns for s in sources)


def write_parquet(df: DataFrame, path: Path) -> None:
    df.write.mode("overwrite").parquet(str(path))
    logger.info("Écrit %s", path)


def fingerprint(config: Any) -> str:
    # sort_keys : deux dicts égaux donnent la même empreinte quel que soit l'ordre des clés.
    payload = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Step:
    """Une étape : ses entrées, ses sorties, la config dont elle dépend, et son build.

    always=True : l'étape tourne à chaque fois (ex. chargement Postgres, dont l'état réel ne peut
    pas se lire dans un fichier : la base a pu être recréée entre deux runs).
    """

    def __init__(
        self,
        name: str,
        inputs: Callable[[dict], list[Path]],
        outputs: Callable[[dict], list[Path]],
        build: Callable[[SparkSession, dict], None],
        always: bool = False,
        config: Callable[[dict], Any] | None = None,
        stamp_dir: Callable[[dict], Path] | None = None,
    ) -> None:
        self.name, self.inputs, self.outputs, self.build = name, inputs, outputs, build
        self.always = always
        self.config = config or (lambda s: None)
        self.stamp_dir = stamp_dir

    def _stamp(self, settings: dict[str, Any]) -> Path | None:
        return self.stamp_dir(settings) / f"{self.name}.json" if self.stamp_dir else None

    def is_up_to_date(self, settings: dict[str, Any]) -> bool:
        if not is_fresh(self.outputs(settings), self.inputs(settings)):
            return False
        stamp = self._stamp(settings)
        if stamp is None:
            return True
        try:
            saved = json.loads(stamp.read_text(encoding="utf-8"))["config"]
        except (OSError, ValueError, KeyError):
            return False
        return saved == fingerprint(self.config(settings))

    def run(self, spark: SparkSession, settings: dict[str, Any], force: bool) -> None:
        if not (force or self.always) and self.is_up_to_date(settings):
            logger.info("Étape %s : à jour, ignorée (--force pour refaire)", self.name)
            return
        logger.info("=== Étape %s ===", self.name)
        stamp = self._stamp(settings)
        if stamp is not None:
            stamp.unlink(missing_ok=True)  # en cas d'échec, l'étape restera périmée
        self.build(spark, settings)
        if stamp is not None:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(
                json.dumps({"config": fingerprint(self.config(settings))}), encoding="utf-8"
            )
