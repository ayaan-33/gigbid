"""Render both LangGraph graphs FROM CODE (make graphs) -> docs/images/*.mmd (Mermaid)."""

from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, g in [("bid_graph", build_bid_graph()), ("conversation_graph", build_conversation_graph())]:
        mmd = g.get_graph().draw_mermaid()
        (OUT / f"{name}.mmd").write_text(mmd)
        print("wrote", OUT / f"{name}.mmd")


if __name__ == "__main__":
    main()
