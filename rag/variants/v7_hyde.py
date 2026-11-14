"""Variant v7: see rag/variants/pipeline.py for the component this preset switches on."""

from rag.index.store import PortfolioIndex
from rag.variants.pipeline import Pipeline
from rag.variants.presets import PRESETS

NAME = "v7_hyde"


def build(index: PortfolioIndex) -> Pipeline:
    return Pipeline(index, PRESETS[NAME], NAME)
