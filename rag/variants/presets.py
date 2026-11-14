"""Variant presets (B2). Each is a Flags preset of rag/variants/pipeline.Pipeline."""

from rag.variants.pipeline import Flags

PRESETS: dict[str, Flags] = {
    "v0_naive": Flags(chunks="fixed"),
    "v1_decompose": Flags(decompose=True),
    "v2_hybrid": Flags(decompose=True, hybrid=True),
    "v3_rerank": Flags(decompose=True, hybrid=True, rerank=True),
    "v4_outcome": Flags(decompose=True, hybrid=True, rerank=True, outcome=True),
    "v5_multivector": Flags(decompose=True, hybrid=True, rerank=True, multivector=True),
    "v6_contextual": Flags(decompose=True, hybrid=True, rerank=True, contextual=True),
    "v7_hyde": Flags(decompose=True, hybrid=True, rerank=True, hyde=True),
    "v8_corrective": Flags(decompose=True, hybrid=True, rerank=True, corrective=True),
}
