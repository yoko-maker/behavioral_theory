from __future__ import annotations

from cogexp.config.loader import load_catalog


def test_repository_experiments_load() -> None:
    catalog = load_catalog()
    assert "pilot_v1" in catalog.experiments
    for exp in catalog.experiments.values():
        for cond in exp.conditions:
            assert all(ref in catalog.variants for ref in cond.variant_refs())
