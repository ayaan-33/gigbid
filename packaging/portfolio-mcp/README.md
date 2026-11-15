# gigbid-portfolio-mcp

An MCP server that lets Claude Desktop, Cursor or any MCP host **search your freelance portfolio
for evidence**: case studies, code repositories, client reviews and past proposals with their
outcomes. The assistant can then write proposals and answer screening questions that cite real
work instead of inventing it.

It's part of [GigBid](https://github.com/), a multi-agent freelancer copilot. It's **read-only**:
it never writes anything anywhere.

## Tools, resources and prompts

| | Name | What it does |
|---|---|---|
| tool | `search_evidence(requirement, k, filters)` | Hybrid (BM25 + embeddings) multi-vector retrieval over your portfolio. Returns items with id, type, source, date and outcome. Filters: `type`, `skills`, `outcome`, `client_industry`, `since`. |
| tool | `get_case_study(id)` | The full case study. |
| tool | `list_skills()` | Every skill your portfolio proves, with evidence counts. |
| resource | `portfolio://case/{key}`, `portfolio://proposal/{key}`, `portfolio://repo/{name}`, `portfolio://cv`, `portfolio://profile` | Load full items. |
| prompt | `answer_screening_question`, `summarise_fit`, `rewrite_with_evidence`, `opening_line` | Ready-made workflows. |

Embeddings (`nomic-embed-text-v1.5`) run locally on CPU. No API key is needed, and your portfolio
never leaves your machine.

## Portfolio folder

```
my-portfolio/            <- GIGBID_PORTFOLIO_DIR
  me/                    <- PORTFOLIO_PERSONA=me
    cv.pdf
    case_studies/*.md    (one project per file; '# Title' + sections)
    repos/<repo>/README.md + source files
    reviews.json         [{"id","project","stars","text","date","client_industry"}]   (optional)
    proposals.jsonl      {"id","job_title","text","outcome":"won|replied|ignored", ...} (optional)
```

`manifest.json` is generated automatically the first time it runs.

## Run it

```bash
uvx gigbid-portfolio-mcp            # stdio, for MCP hosts
```

Or with Docker / HTTP (Streamable HTTP at `/mcp`, Bearer token required):

```bash
MCP_BEARER_TOKEN=change-me uvx gigbid-portfolio-mcp --http
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "portfolio": {
      "command": "uvx",
      "args": ["gigbid-portfolio-mcp"],
      "env": { "GIGBID_PORTFOLIO_DIR": "/Users/you/my-portfolio", "PORTFOLIO_PERSONA": "me" }
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)
Use the same `command`, `args` and `env` as above.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GIGBID_PORTFOLIO_DIR` | bundled demo portfolios | Folder that contains your portfolio folder(s). |
| `PORTFOLIO_PERSONA` | `ai_ml_engineer` | Which sub-folder to serve. |
| `RAG_VARIANT` | from config | Retrieval pipeline (`v0_naive` … `v8_corrective`). |
| `MCP_BEARER_TOKEN` | — | Required for `--http`. |

MIT licence.
