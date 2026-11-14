"""Preprocess the Kaggle downloads (data/raw/**) into GigBid's real-data artefacts.

Outputs
  data/processed/real_jobs.jsonl      cleaned real postings with descriptions (git-ignored, large)
  data/derived/market_stats.json      price percentiles by category x budget type   (committed)
  data/derived/contract_rates.json    realised hourly rates / totals by category      (committed)
  data/derived/client_priors.json     client-history distributions                    (committed)
  data/derived/freelancer_priors.json freelancer outcome distributions                (committed)
  data/derived/scam_cues.json         aggregate fraud-cue term lifts (trial-1, licence unknown:
                                      aggregate statistics only, no rows kept)        (committed)
  data/derived/real_jobs_sample.jsonl 300-row sample for tests and the data card       (committed)
  data/derived/preprocess_report.json row counts, drops, dedups                       (committed)

Run:  uv run python -m scripts.data.preprocess_kaggle
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.data.taxonomy import categorize, extract_skills

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
DERIVED = ROOT / "data" / "derived"

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d")
URL = re.compile(r"https?://\S+|www\.\S+")
WS = re.compile(r"\s+")

report: dict = {"sources": {}}


def scrub(text: str) -> str:
    text = str(text or "")
    text = EMAIL.sub("[email]", text)
    text = URL.sub("[link]", text)
    text = PHONE.sub("[phone]", text)
    return WS.sub(" ", text).strip()


def jid(*parts: str) -> str:
    return "rj_" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:14]


def money(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).replace("$", "").replace(",", "").strip().upper()
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000.0, s[:-1]
    s = s.rstrip("+")
    try:
        return float(s) * mult
    except ValueError:
        return None


APPLICANTS = {"less than 5": 3, "5 to 10": 7, "10 to 15": 12, "15 to 20": 17, "20 to 50": 35, "50+": 60}


# --------------------------------------------------------------------------- jobs with descriptions


def load_50k() -> pd.DataFrame:
    f = RAW / "upwork_50k" / "upwork-jobs.csv"
    d = pd.read_csv(f)
    n0 = len(d)
    d = d.dropna(subset=["title", "description"])
    d["is_hourly"] = d["is_hourly"].astype(str).str.lower().eq("true")
    out = pd.DataFrame({
        "source": "kaggle_upwork_50k_2024",
        "link": d["link"],
        "title": d["title"].astype(str),
        "description": d["description"].astype(str),
        "published_date": d["published_date"],
        "budget_type": np.where(d["is_hourly"], "hourly", "fixed"),
        "budget": d["budget"],
        "hourly_low": d["hourly_low"],
        "hourly_high": d["hourly_high"],
        "country": d["country"],
    })
    report["sources"]["upwork_50k"] = {"rows_raw": n0, "rows_with_description": len(out)}
    return out


def load_60k() -> pd.DataFrame:
    f = RAW / "upwork_60k" / "Final_Upwork_Dataset.csv"
    d = pd.read_csv(f, low_memory=False)
    n0 = len(d)
    d = d.dropna(subset=["Job Title", "Description"])
    cats = [c for c in d.columns if c.startswith("Category_")]
    hourly = d["Payment_type"].astype(str).str.lower().str.startswith("hourly")
    out = pd.DataFrame({
        "source": "kaggle_upwork_60k_2023",
        "link": d["Job_URL"],
        "title": d["Job Title"].astype(str),
        "description": d["Description"].astype(str),
        "published_date": None,
        "budget_type": np.where(hourly, "hourly", "fixed"),
        "budget": d["Job_Cost"].map(money),
        "hourly_low": d["Start_rate"].map(money),
        "hourly_high": d["End_rate"].map(money),
        "country": d["Client_Country"],
        "experience_level": d["EX_level_demand"].astype(str).str.lower(),
        "connects_cost": pd.to_numeric(d["Connects_Num"], errors="coerce"),
        "applicants": d["Applicants_Num"].astype(str).str.lower().str.strip().map(APPLICANTS),
        "client_spent": d["Spent($)"].map(money),
        "payment_verified": d["Payment_Situation"].astype(str).str.lower().str.contains(r"\bverified") &
        ~d["Payment_Situation"].astype(str).str.lower().str.contains("unverified"),
        "client_rating": pd.to_numeric(d["Rating"], errors="coerce"),
        "client_feedback_num": pd.to_numeric(d["Feedback_Num"], errors="coerce"),
        "tags": [[x for x in row if isinstance(x, str) and x and x != "nan"] for row in d[cats].itertuples(index=False)],
    })
    report["sources"]["upwork_60k"] = {"rows_raw": n0, "rows_with_description": len(out)}
    return out


def build_real_jobs() -> pd.DataFrame:
    d = pd.concat([load_50k(), load_60k()], ignore_index=True)
    d["description"] = d["description"].map(scrub)
    d["title"] = d["title"].map(scrub)
    d = d[d["description"].str.len() >= 80]
    before = len(d)
    d["norm"] = (d["title"].str.lower().str[:80] + "|" + d["description"].str.lower().str[:200])
    d = d.drop_duplicates(subset=["norm"]).drop(columns=["norm"])
    report["dedup_removed"] = before - len(d)
    d["skills"] = [extract_skills(f"{t} {x} {' '.join(map(str, g)) if isinstance(g, list) else ''}")
                   for t, x, g in zip(d["title"], d["description"], d.get("tags", [None] * len(d)), strict=False)]
    d["category"] = [categorize(t, x, s) for t, x, s in zip(d["title"], d["description"], d["skills"], strict=False)]
    d["id"] = [jid(str(link), t) for link, t in zip(d["link"], d["title"], strict=False)]
    d = d.drop(columns=["link"])
    report["real_jobs"] = {"rows": len(d), "by_category": d["category"].value_counts().to_dict()}
    return d


# --------------------------------------------------------------------------- price statistics


def load_200k_prices() -> pd.DataFrame:
    frames = []
    for f in sorted((RAW / "upwork_200k").glob("*.csv")):
        x = pd.read_csv(f, usecols=["title", "is_hourly", "hourly_low", "hourly_high", "budget"])
        frames.append(x)
    d = pd.concat(frames, ignore_index=True)
    report["sources"]["upwork_200k"] = {"rows_raw": len(d)}
    d["is_hourly"] = d["is_hourly"].astype(str).str.lower().eq("true")
    d["skills"] = d["title"].astype(str).map(extract_skills)
    d["category"] = [categorize(str(t), "", s) for t, s in zip(d["title"], d["skills"], strict=False)]
    return pd.DataFrame({
        "category": d["category"],
        "budget_type": np.where(d["is_hourly"], "hourly", "fixed"),
        "budget": d["budget"],
        "hourly_low": d["hourly_low"],
        "hourly_high": d["hourly_high"],
    })


def pct(series: pd.Series) -> dict | None:
    s = series.dropna()
    s = s[(s > 0) & (s < s.quantile(0.995))] if len(s) > 50 else s[s > 0]
    if len(s) < 20:
        return None
    q = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).tolist()
    return {"n": int(len(s)), "p10": q[0], "p25": q[1], "median": q[2], "p75": q[3], "p90": q[4]}


def market_stats(real: pd.DataFrame) -> dict:
    p200 = load_200k_prices()
    cols = ["category", "budget_type", "budget", "hourly_low", "hourly_high"]
    allp = pd.concat([real[cols], p200[cols]], ignore_index=True)
    allp["hourly_mid"] = allp[["hourly_low", "hourly_high"]].mean(axis=1)
    out: dict = {}
    for cat, g in allp.groupby("category"):
        out[cat] = {
            "fixed": pct(g.loc[g["budget_type"] == "fixed", "budget"]),
            "hourly": pct(g.loc[g["budget_type"] == "hourly", "hourly_mid"]),
        }
    return out


def contract_rates() -> dict:
    f = RAW / "contracts_1_3m" / "contracts.csv"
    acc: dict[str, dict[str, list[float]]] = {}
    n = 0
    for chunk in pd.read_csv(f, usecols=["job_title", "total_paid", "hourly_rate"], chunksize=200_000):
        n += len(chunk)
        sample = chunk.sample(frac=0.25, random_state=7)
        cats = [categorize(str(t)) for t in sample["job_title"]]
        for cat, paid, rate in zip(cats, sample["total_paid"], sample["hourly_rate"], strict=False):
            a = acc.setdefault(cat, {"total_paid": [], "hourly_rate": []})
            if paid and paid > 0:
                a["total_paid"].append(float(paid))
            if rate and rate > 0:
                a["hourly_rate"].append(float(rate))
    report["sources"]["contracts_1_3m"] = {"rows_raw": n, "sampled_frac": 0.25}
    return {c: {k: pct(pd.Series(v)) for k, v in d.items()} for c, d in acc.items()}


def client_priors(real: pd.DataFrame) -> dict:
    d = real[real["source"] == "kaggle_upwork_60k_2023"]
    return {
        "payment_verified_rate": round(float(d["payment_verified"].mean()), 4),
        "client_spent": pct(d["client_spent"]),
        "client_spent_zero_rate": round(float((d["client_spent"].fillna(0) == 0).mean()), 4),
        "client_rating": pct(d["client_rating"]),
        "applicants": pct(d["applicants"]),
        "connects_cost": d["connects_cost"].dropna().astype(int).value_counts().sort_index().to_dict(),
        "experience_level": d["experience_level"].value_counts(normalize=True).round(4).to_dict(),
    }


def freelancer_priors() -> dict:
    d = pd.read_csv(RAW / "freelancer_success" / "freelancer_gig_success_dataset.csv")
    report["sources"]["freelancer_success"] = {"rows_raw": len(d)}
    out = {}
    for skill, g in d.groupby("primary_skill"):
        out[skill] = {
            "hourly_rate_usd": pct(g["hourly_rate_usd"]),
            "job_success_rate": pct(g["job_success_rate"]),
            "repeat_client_rate": pct(g["repeat_client_rate"]),
            "avg_response_time_hrs": pct(g["avg_response_time_hrs"]),
            "n": int(len(g)),
        }
    return out


def scam_cues() -> dict:
    """Aggregate term lifts for fraudulent postings. Licence of trial-1 is unknown, so only
    aggregate statistics leave this function; no rows are written anywhere."""
    f = RAW / "trial_1" / "processed_labeled_dataset_without_encoding.xlsx"
    if not f.exists():
        return {}
    d = pd.read_excel(f)
    report["sources"]["trial_1"] = {"rows_raw": len(d), "usage": "aggregate term statistics only"}
    d = d[d["fraudulent"].notna()]
    d["text"] = (d["job_desc"].fillna("").astype(str) + " " + d["skills_desc"].fillna("").astype(str)).str.lower()
    y = pd.to_numeric(d["fraudulent"], errors="coerce").fillna(0).astype(int).eq(1)
    tok = d["text"].str.findall(r"[a-z]{4,}")
    fraud, legit = Counter(), Counter()
    for words, is_f in zip(tok, y, strict=False):
        (fraud if is_f else legit).update(set(words) if isinstance(words, list) else set())
    nf, nl = max(1, int(y.sum())), max(1, int((~y).sum()))
    lifts = []
    for w, c in fraud.items():
        if c < 15:
            continue
        pf, pl = c / nf, (legit[w] + 1) / nl
        lifts.append((w, round(pf / pl, 2), c))
    lifts.sort(key=lambda t: -t[1])
    return {"n_fraud": nf, "n_legit": nl, "top_terms": [{"term": w, "lift": lf, "count": c} for w, lf, c in lifts[:60]]}


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    DERIVED.mkdir(parents=True, exist_ok=True)
    real = build_real_jobs()
    keep = ["id", "source", "title", "description", "category", "skills", "budget_type", "budget",
            "hourly_low", "hourly_high", "country", "published_date", "experience_level",
            "connects_cost", "applicants", "client_spent", "payment_verified", "client_rating"]
    with open(PROC / "real_jobs.jsonl", "w", encoding="utf-8") as fh:
        for rec in real[keep].to_dict(orient="records"):
            rec = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rec.items()}
            rec["real"] = True
            fh.write(json.dumps(rec, default=str) + "\n")
    sample = real[keep].sample(300, random_state=1)
    with open(DERIVED / "real_jobs_sample.jsonl", "w", encoding="utf-8") as fh:
        for rec in sample.to_dict(orient="records"):
            rec = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rec.items()}
            fh.write(json.dumps({**rec, "real": True}, default=str) + "\n")
    for name, fn in [("market_stats", lambda: market_stats(real)), ("contract_rates", contract_rates),
                     ("client_priors", lambda: client_priors(real)), ("freelancer_priors", freelancer_priors),
                     ("scam_cues", scam_cues)]:
        (DERIVED / f"{name}.json").write_text(json.dumps(fn(), indent=1, default=str))
        print("wrote", name)
    (DERIVED / "preprocess_report.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
