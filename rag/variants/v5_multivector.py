"""Variant v5: see rag/variants/pipeline.py for the component this preset switches on."""

from rag.index.store import PortfolioIndex
from rag.variants.pipeline import Pipeline
from rag.variants.presets import PRESETS

NAME = "v5_multivector"


def build(index: PortfolioIndex) -> Pipeline:
    return Pipeline(index, PRESETS[NAME], NAME)
