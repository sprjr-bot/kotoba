"""Japanese ingest callables for the generic dataset pipeline.

Each callable matches the pipeline contract
``ingest(source_path, dataset_dir, descriptor)`` and builds a SQLite index.
The SQLite schema builders themselves live in :mod:`kotoba.localdict`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from kotoba import localdict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from kotoba.datasets import DatasetDescriptor


def ingest_jmdict(source: Path, dataset_dir: Path, descriptor: "DatasetDescriptor | None" = None) -> None:
    """Build the JMdict index from the extracted ``words[]`` JSON file."""
    localdict.build_jmdict_index(source, dataset_dir)


def ingest_kanjidic2(source: Path, dataset_dir: Path, descriptor: "DatasetDescriptor | None" = None) -> None:
    """Build the KANJIDIC2 index from the extracted ``characters[]`` JSON file."""
    localdict.build_kanjidic2_index(source, dataset_dir)


def ingest_kradfile(source: Path, dataset_dir: Path, descriptor: "DatasetDescriptor | None" = None) -> None:
    """Build the Kradfile component index."""
    localdict.build_kradfile_index(source, dataset_dir)


def ingest_radkfile(source: Path, dataset_dir: Path, descriptor: "DatasetDescriptor | None" = None) -> None:
    """Build the Radkfile radical index."""
    localdict.build_radkfile_index(source, dataset_dir)
