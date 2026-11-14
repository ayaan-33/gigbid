"""Generate the three SYNTHETIC persona corpora from scripts/data/archetypes.py.

data/personas/<persona_id>/
  profile.json                  persona summary (synthetic: true)
  cv.md, cv.pdf                 CV (projects named with alias #2)
  case_studies/<key>.md         one per project (alias #1), YAML front-matter metadata
  repos/<repo>/README.md, src/* code repos (some READMEs deliberately vague)
  reviews.json                  client reviews
  proposals.jsonl               ~150 past proposals labelled won / replied / ignored (alias #3)
  manifest.json                 every evidence item with metadata + project skills (gold source)
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from scripts.data import code_snippets as cs
from scripts.data.archetypes import PERSONAS, PROJECTS
from scripts.data.taxonomy import CATEGORY_SKILLS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "personas"
REAL_JOBS = ROOT / "data" / "processed" / "real_jobs.jsonl"
REAL_SAMPLE = ROOT / "data" / "derived" / "real_jobs_sample.jsonl"

IMPLIED_PHRASES = {
    "Docker": "shipped it as a container image so their ops team could run it anywhere",
    "LangChain": "orchestrated the retrieval and tool calls as an explicit state machine",
    "PostgreSQL": "kept everything in their existing relational database with proper migrations",
    "pandas": "did the feature work in dataframes and kept every transformation in versioned notebooks",
    "SQL": "pulled the history straight from their warehouse with window-function queries",
    "Airflow": "scheduled the weekly refresh as a DAG with retries and alerting",
    "Hugging Face": "started from an open pretrained transformer checkpoint",
    "PyTorch": "wrote the training loop myself so we controlled augmentation and early stopping",
    "MLOps": "versioned every model and promoted it through staging with tracked metrics",
    "FastAPI": "wrapped it in a small typed Python web service",
    "REST API": "exposed it over a documented HTTP API their other systems could call",
    "CI/CD": "ran the whole suite automatically on every pull request",
    "Statistics": "reported confidence intervals rather than single numbers",
    "Vector DB": "stored embeddings next to the source rows so retrieval stayed consistent",
    "AWS": "deployed on their existing cloud account with least-privilege roles",
    "Testing": "covered the critical paths with automated tests before refactoring",
    "Kubernetes": "rolled it out on their container cluster with health probes",
    "Redis": "added an in-memory cache for the hottest reads",
    "TypeScript": "kept the whole codebase strictly typed",
    "Tailwind CSS": "built a small utility-first design system",
    "WebSockets": "pushed updates to the browser over a persistent connection",
    "HTML/CSS": "hand-built semantic, responsive markup",
    "SEO": "kept every URL and meta tag so search rankings held",
    "Celery": "moved slow work to a background job queue",
    "Node.js": "wrote the server side in JavaScript to share types with the frontend",
    "JavaScript": "kept the frontend dependency-light",
    "ETL": "built the extract-clean-load steps so the numbers refresh without anyone touching them",
    "Excel": "left them with a workbook the finance team could still open and audit",
    "Data Visualization": "designed the charts so a manager can read them in ten seconds",
    "Snowflake": "ran the models on their cloud warehouse",
    "Python": "scripted the repetitive steps",
    "R": "checked the statistical models in a second toolkit",
}

SURNAMES = ["Harbor", "Pine", "Atlas", "Juniper", "Copper", "Summit", "Bright", "Lumen", "North", "Kestrel",
            "Orchid", "Granite", "Maple", "Signal", "Tidal", "Cobalt", "Willow", "Vertex", "Saffron", "Beacon"]
SUFFIX = ["Labs", "Group", "Co.", "Analytics", "Health", "Retail", "Logistics", "Systems", "Partners", "Studio"]


def company(rng: random.Random) -> str:
    return f"{rng.choice(SURNAMES)} {rng.choice(SUFFIX)}"


_RANGE = re.compile(r"\{([\d.]+)\.\.([\d.]+)\}")


def fill(template: str, rng: random.Random) -> str:
    def repl(m: re.Match[str]) -> str:
        lo, hi = m.group(1), m.group(2)
        if "." in lo or "." in hi:
            return f"{rng.uniform(float(lo), float(hi)):.2f}"
        return str(rng.randint(int(lo), int(hi)))

    return _RANGE.sub(repl, template)


# --------------------------------------------------------------------------- project instances


def instances(pid: str, rng: random.Random) -> list[dict]:
    persona = PERSONAS[pid]
    start = date(2026, 9, 30) - timedelta(days=365 * persona["years"])
    projs = []
    for i, a in enumerate(PROJECTS[pid]):
        d = start + timedelta(days=int((i + rng.random()) * 365 * persona["years"] / len(PROJECTS[pid])))
        metrics = [fill(m, rng) for m in a["metrics"]]
        projs.append({
            **a,
            "persona": pid,
            "industry": rng.choice(a["industries"]),
            "client": company(rng),
            "date": d.isoformat(),
            "weeks": rng.randint(3, 14),
            "metrics_filled": metrics,
            "all_skills": sorted(set(a["skills"]) | set(a["implied"])),
        })
    return projs


# --------------------------------------------------------------------------- case studies


def case_study(p: dict, rng: random.Random) -> str:
    implied = [IMPLIED_PHRASES.get(s, "") for s in p["implied"]]
    implied = [x for x in implied if x]
    steps = list(p["approach"])
    for ph in implied:
        steps.insert(rng.randint(1, len(steps)), ph)
    front = {
        "id": f"{p['persona']}:case:{p['key']}",
        "type": "case_study",
        "project": p["key"],
        "title": p["names"][0],
        "client_industry": p["industry"],
        "date": p["date"],
        "skills": p["skills"],
        "synthetic": True,
    }
    opener = rng.choice([
        f"A {p['industry']} client, {p['client']}, came to me because {p['problem']}.",
        f"{p['client']} ({p['industry']}) had a familiar problem: {p['problem']}.",
        f"When I started with {p['client']}, a {p['industry']} business, {p['problem']}.",
    ])
    body = [
        "---", json.dumps(front, ensure_ascii=False), "---", "",
        f"# {p['names'][0]}", "",
        "## Context", "", opener, "",
        "## What I did", "",
        *[f"- {s[0].upper() + s[1:]}." for s in steps], "",
        "## Results", "",
        *[f"- {m[0].upper() + m[1:]}." for m in p["metrics_filled"]], "",
        f"Engagement: {p['weeks']} weeks, finished {p['date'][:7]}.", "",
        "## Stack", "", ", ".join(p["skills"]), "",
    ]
    return "\n".join(body)


# --------------------------------------------------------------------------- CV


def cv_markdown(pid: str, projs: list[dict], rng: random.Random) -> str:
    per = PERSONAS[pid]
    named = sorted({s for p in projs for s in p["skills"]})
    lines = [
        f"# {per['name']} (synthetic persona)", "",
        f"**{per['headline']}**  ", f"{per['location']} · {per['years']} years freelancing · ${per['hourly_rate']}/hr", "",
        "## Summary", "",
        f"I help teams turn messy problems into shipped, measurable results. Voice: {per['voice']}.", "",
        "## Skills", "", ", ".join(named), "",
        "## Selected freelance work", "",
    ]
    for p in sorted(projs, key=lambda x: x["date"], reverse=True):
        lines.append(f"**{p['names'][1].capitalize()}** — {p['industry']} client, {p['date'][:4]}  ")
        lines.append(f"{p['metrics_filled'][0].capitalize()}; {p['metrics_filled'][1]}.")
        lines.append("")
    lines += ["## Education", "", per["education"], ""]
    return "\n".join(lines)


def cv_pdf(md: str, path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    story = []
    for line in md.splitlines():
        line = line.replace("**", "").replace("&", "&amp;").rstrip()
        if line.startswith("# "):
            story.append(Paragraph(line[2:], styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], styles["Heading2"]))
        elif line:
            story.append(Paragraph(line.strip(), styles["BodyText"]))
        else:
            story.append(Spacer(1, 4))
    SimpleDocTemplate(str(path), pagesize=A4, title="CV (synthetic)").build(story)


# --------------------------------------------------------------------------- repos


def repo_name(p: dict) -> str:
    return p["key"].replace("_", "-")


def build_repo(p: dict, root: Path) -> dict:
    rdir = root / repo_name(p)
    (rdir / "src").mkdir(parents=True, exist_ok=True)
    skills = p["all_skills"]
    reqs: list[str] = []
    py_parts, ts_files = [], {}
    for s in skills:
        if s in cs.PY and cs.PY[s][1]:
            dep, code = cs.PY[s]
            py_parts.append(code.replace("{title}", p["names"][0]))
            reqs += [x for x in dep.splitlines() if x]
        if s in cs.TS:
            ts_files[f"src/{s.lower().replace('.', '').replace(' ', '_').replace('/', '_')}.tsx"] = cs.TS[s]
    if py_parts:
        (rdir / "src" / "main.py").write_text("\n\n".join(py_parts))
        (rdir / "requirements.txt").write_text("\n".join(sorted(set(reqs))) + "\n")
    for f, code in ts_files.items():
        (rdir / f).write_text(code)
    if ts_files:
        (rdir / "package.json").write_text(json.dumps({"name": repo_name(p), "private": True,
                                                         "dependencies": _ts_deps(skills)}, indent=2))
    if "Docker" in skills:
        (rdir / "Dockerfile").write_text(cs.DOCKERFILE)
    if "dbt" in skills:
        (rdir / "models").mkdir(exist_ok=True)
        (rdir / "models" / "fct_orders.sql").write_text(cs.SQL_DBT)
    if "Power BI" in skills:
        (rdir / "measures.dax").write_text(cs.DAX)
    if p["repo"] == "clear":
        readme = (f"# {repo_name(p)}\n\n{p['names'][0]} for a {p['industry']} client.\n\n"
                  f"Problem: {p['problem']}.\n\nStack: {', '.join(p['skills'])}.\n\n"
                  f"Results: {'; '.join(p['metrics_filled'][:2])}.\n\n_Synthetic portfolio repo._\n")
    else:  # deliberately vague: relevance only visible in the code
        readme = f"# {repo_name(p)}\n\nInternal utilities and scripts from a client engagement. See `src/`.\n\n_Synthetic portfolio repo._\n"
    (rdir / "README.md").write_text(readme)
    files = sorted(str(x.relative_to(rdir)) for x in rdir.rglob("*") if x.is_file())
    return {"repo": repo_name(p), "files": files, "readme_style": p["repo"]}


def _ts_deps(skills: list[str]) -> dict:
    m = {"React": {"react": "^18.3.1"}, "Next.js": {"next": "^14.2.5"}, "Stripe": {"stripe": "^16.0.0"},
         "WebSockets": {"socket.io": "^4.7.5"}, "GraphQL": {"@apollo/server": "^4.10.4", "dataloader": "^2.2.2"},
         "Supabase": {"@supabase/supabase-js": "^2.45.0"}, "Vue": {"vue": "^3.4.0"},
         "Tailwind CSS": {"tailwindcss": "^3.4.7"}, "Node.js": {"express": "^4.19.2"}}
    out: dict = {}
    for s in skills:
        out.update(m.get(s, {}))
    return out


# --------------------------------------------------------------------------- reviews


REVIEW_TEMPLATES = [
    "{name} understood our problem in the first call. {metric}. Clear updates every few days.",
    "Very solid work on the {alias}. {metric}. Would hire again.",
    "Delivered on time and explained every trade-off. {metric}.",
    "Communication was excellent and the code is clean. {metric}. A couple of revisions needed on the final report.",
    "Great to work with. The {alias} is now part of our daily routine.",
]


def reviews(pid: str, projs: list[dict], rng: random.Random) -> list[dict]:
    out = []
    first = PERSONAS[pid]["name"].split()[0]
    for p in rng.sample(projs, k=min(13, len(projs))):
        stars = rng.choices([5, 4, 3], weights=[0.72, 0.22, 0.06])[0]
        t = rng.choice(REVIEW_TEMPLATES).format(
            name=first, alias=p["names"][rng.randint(0, 2)], metric=p["metrics_filled"][rng.randint(0, 2)].capitalize()
        )
        out.append({"id": f"{pid}:review:{p['key']}", "type": "review", "project": p["key"], "stars": stars,
                    "client_industry": p["industry"], "date": p["date"], "text": t, "synthetic": True})
    return out


# --------------------------------------------------------------------------- past proposals


def load_real_jobs() -> list[dict]:
    src = REAL_JOBS if REAL_JOBS.exists() else REAL_SAMPLE
    with open(src, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


GENERIC = [
    "Dear Hiring Manager, I am a highly experienced professional and I have read your job post carefully.",
    "Hello Sir/Madam, I am very passionate about this kind of work and I can do this job perfectly.",
    "Hi there! I am interested in your project and I am the best fit for it.",
]


def proposal(pid: str, job: dict, projs: list[dict], rng: random.Random, idx: int) -> dict:
    per = PERSONAS[pid]
    jskills = set(job.get("skills") or [])
    ranked = sorted(projs, key=lambda p: -len(jskills & set(p["all_skills"])))
    relevant = [p for p in ranked if jskills & set(p["all_skills"])]
    style = rng.choices(["generic", "problem_led", "question_led"], weights=[0.35, 0.45, 0.20])[0]
    n_cite = rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.28, 0.12])[0]
    use_relevant = rng.random() < 0.65
    pool = relevant if (use_relevant and relevant) else rng.sample(projs, k=len(projs))
    cited = pool[:n_cite]
    title = job["title"].strip().rstrip(".")
    if style == "generic":
        opening = rng.choice(GENERIC)
    elif style == "problem_led":
        opening = f"You need {title.lower()} done properly, without a long ramp-up."
    else:
        opening = f"Quick question before anything else: what does success look like for '{title}' in the first two weeks?"
    body = []
    for p in cited:
        metric = p["metrics_filled"][rng.randint(0, 2)] if rng.random() < 0.75 else ""
        body.append(f"I recently delivered a {p['names'][2]} for a {p['industry']} client" + (f" ({metric})." if metric else "."))
    if jskills:
        body.append(f"For your project I would start with {', '.join(sorted(jskills)[:3])} and share a working first milestone early.")
    if style != "generic" and rng.random() < 0.6:
        body.append("I would keep scope tight, agree acceptance criteria up front and send short progress notes.")
    filler = " I am hardworking, reliable and available any time, and I always deliver high quality work on time." * rng.choice([0, 0, 1, 2])
    close = f"Best regards,\n{per['name'].split()[0]}"
    text = "\n\n".join([opening, " ".join(body) + filler, close]).strip()
    words = len(text.split())
    has_metric = bool(re.search(r"\d", " ".join(body)))
    n_rel = sum(1 for p in cited if jskills & set(p["all_skills"]))
    in_cat = job.get("category") in per["categories"] + per["secondary"]
    score = (0.95 * (style != "generic") + 0.7 * min(n_rel, 2) + 0.5 * has_metric
             - 0.6 * (words > 260) + 0.6 * in_cat + rng.gauss(0, 0.55))
    p_reply = 1 / (1 + math.exp(-(score - 2.45) * 1.6))
    replied = rng.random() < p_reply
    won = replied and rng.random() < 0.38
    outcome = "won" if won else ("replied" if replied else "ignored")
    budget = job.get("budget") or job.get("hourly_high") or per["hourly_rate"]
    return {
        "id": f"{pid}:proposal:p{idx:03d}",
        "type": "proposal",
        "job_title": job["title"],
        "job_category": job.get("category"),
        "job_skills": sorted(jskills),
        "job_source_id": job.get("id"),
        "text": text,
        "bid_amount": round(float(budget) * rng.uniform(0.8, 1.1), 2) if budget else None,
        "cited_projects": [p["key"] for p in cited],
        "features": {"opening": style, "n_cited": n_cite, "n_relevant": n_rel, "has_metric": has_metric, "words": words},
        "outcome": outcome,
        "date": (date(2026, 9, 30) - timedelta(days=rng.randint(10, 900))).isoformat(),
        "synthetic": True,
    }


def proposals(pid: str, projs: list[dict], jobs: list[dict], rng: random.Random, n: int = 150) -> list[dict]:
    per = PERSONAS[pid]
    mine = [j for j in jobs if j.get("category") in per["categories"]]
    adjacent = [j for j in jobs if j.get("category") in per["secondary"]]
    other = [j for j in jobs if j.get("category") not in per["categories"] + per["secondary"]]
    picks = rng.sample(mine, k=min(len(mine), int(n * 0.72)))
    picks += rng.sample(adjacent, k=min(len(adjacent), int(n * 0.14)))
    picks += rng.sample(other, k=n - len(picks))
    return [proposal(pid, j, projs, rng, i) for i, j in enumerate(picks)]


# --------------------------------------------------------------------------- main


def build_persona(pid: str, jobs: list[dict], seed: int = 2026) -> dict:
    rng = random.Random(f"{seed}:{pid}")
    out = OUT / pid
    if out.exists():
        shutil.rmtree(out)
    (out / "case_studies").mkdir(parents=True)
    projs = instances(pid, rng)
    manifest: list[dict] = []
    for p in projs:
        (out / "case_studies" / f"{p['key']}.md").write_text(case_study(p, rng))
        manifest.append({"id": f"{pid}:case:{p['key']}", "type": "case_study", "project": p["key"],
                         "title": p["names"][0], "path": f"case_studies/{p['key']}.md", "date": p["date"],
                         "client_industry": p["industry"], "skills": p["skills"]})
    md = cv_markdown(pid, projs, rng)
    (out / "cv.md").write_text(md)
    cv_pdf(md, out / "cv.pdf")
    manifest.append({"id": f"{pid}:cv", "type": "cv", "project": None, "title": "CV", "path": "cv.pdf",
                     "date": "2026-10-01", "client_industry": None, "skills": sorted({s for p in projs for s in p["skills"]})})
    repo_projects = [p for i, p in enumerate(projs) if i % 2 == 0][:10]
    for p in repo_projects:
        info = build_repo(p, out / "repos")
        manifest.append({"id": f"{pid}:repo:{info['repo']}", "type": "repo", "project": p["key"],
                         "title": info["repo"], "path": f"repos/{info['repo']}", "date": p["date"],
                         "client_industry": p["industry"], "skills": p["all_skills"],
                         "readme_style": info["readme_style"], "files": info["files"]})
    revs = reviews(pid, projs, rng)
    (out / "reviews.json").write_text(json.dumps(revs, indent=1))
    for r in revs:
        manifest.append({k: r[k] for k in ("id", "type", "project", "date", "client_industry")} |
                        {"title": f"Review ({r['stars']}★)", "path": "reviews.json", "skills": []})
    props = proposals(pid, projs, jobs, rng)
    with open(out / "proposals.jsonl", "w") as fh:
        for pr in props:
            fh.write(json.dumps(pr) + "\n")
    for pr in props:
        manifest.append({"id": pr["id"], "type": "proposal", "project": (pr["cited_projects"] or [None])[0],
                         "title": f"Proposal: {pr['job_title'][:60]}", "path": "proposals.jsonl",
                         "date": pr["date"], "client_industry": None, "skills": pr["job_skills"],
                         "outcome": pr["outcome"], "cited_projects": pr["cited_projects"]})
    per = PERSONAS[pid]
    profile = {"persona_id": pid, **per, "synthetic": True,
               "skills": sorted({s for p in projs for s in p["skills"]}),
               "capabilities": sorted({s for p in projs for s in p["all_skills"]}),
               "category_skills": sorted(set().union(*[CATEGORY_SKILLS[c] for c in per["categories"]])),
               "projects": [{k: p[k] for k in ("key", "names", "skills", "implied", "industry", "client", "date", "metrics_filled")} for p in projs]}
    (out / "profile.json").write_text(json.dumps(profile, indent=1))
    (out / "manifest.json").write_text(json.dumps({"persona_id": pid, "synthetic": True, "items": manifest}, indent=1))
    counts = {t: sum(1 for m in manifest if m["type"] == t) for t in ["case_study", "cv", "repo", "review", "proposal"]}
    counts["outcomes"] = {o: sum(1 for p in props if p["outcome"] == o) for o in ["won", "replied", "ignored"]}
    return counts


def main() -> None:
    jobs = load_real_jobs()
    summary = {pid: build_persona(pid, jobs) for pid in PERSONAS}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
