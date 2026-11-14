"""Shared taxonomy: GigBid job categories and a canonical skill dictionary with aliases.

Used by preprocessing (real Kaggle jobs), synthetic generation, retrieval metadata and the
Fit Matcher, so the same skill is spelled the same way everywhere.
"""

from __future__ import annotations

import re
from functools import cache

CATEGORIES = ["ai_ml", "web_dev", "data_analysis", "mobile", "design", "writing", "marketing", "other"]

# canonical skill -> aliases (lower-case, matched on word boundaries)
SKILLS: dict[str, list[str]] = {
    # --- AI / ML
    "Python": ["python", "python3"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "keras"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "XGBoost": ["xgboost", "lightgbm", "catboost", "gradient boosting"],
    "LLM": ["llm", "llms", "large language model", "gpt-4", "gpt4", "chatgpt", "openai api", "claude", "llama"],
    "RAG": ["rag", "retrieval augmented", "retrieval-augmented", "vector search", "semantic search"],
    "LangChain": ["langchain", "langgraph", "llamaindex", "llama index"],
    "Vector DB": ["pinecone", "weaviate", "qdrant", "chroma", "chromadb", "pgvector", "faiss", "milvus"],
    "NLP": ["nlp", "natural language processing", "text classification", "named entity", "ner", "sentiment analysis", "spacy"],
    "Computer Vision": ["computer vision", "opencv", "object detection", "yolo", "image classification", "segmentation"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"],
    "Fine-tuning": ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora"],
    "MLOps": ["mlops", "mlflow", "model deployment", "kubeflow", "sagemaker", "vertex ai", "weights & biases", "wandb"],
    "Time Series": ["time series", "forecasting", "prophet", "arima"],
    "Recommendation Systems": ["recommendation system", "recommender", "collaborative filtering"],
    "Chatbot": ["chatbot", "chat bot", "conversational ai", "voice agent", "ai agent", "ai agents"],
    "Speech": ["speech to text", "whisper", "tts", "text to speech", "asr"],
    "Web Scraping": ["web scraping", "scraper", "scrapy", "beautifulsoup", "selenium", "crawler"],
    # --- Web
    "JavaScript": ["javascript", "js", "es6"],
    "TypeScript": ["typescript", "ts"],
    "React": ["react", "reactjs", "react.js"],
    "Next.js": ["next.js", "nextjs", "next js"],
    "Vue": ["vue", "vuejs", "vue.js", "nuxt"],
    "Angular": ["angular"],
    "Node.js": ["node.js", "nodejs", "node js", "express", "expressjs", "nestjs"],
    "Django": ["django"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "PHP": ["php", "laravel"],
    "WordPress": ["wordpress", "woocommerce", "elementor"],
    "Shopify": ["shopify", "liquid"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql", "mariadb"],
    "MongoDB": ["mongodb", "mongo", "mongoose"],
    "Redis": ["redis"],
    "GraphQL": ["graphql", "apollo"],
    "REST API": ["rest api", "restful", "api integration", "api development"],
    "Tailwind CSS": ["tailwind", "tailwindcss"],
    "HTML/CSS": ["html", "css", "html5", "css3", "sass", "scss"],
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "GCP": ["gcp", "google cloud", "firebase", "bigquery"],
    "Azure": ["azure"],
    "Docker": ["docker", "docker compose", "containerization"],
    "Kubernetes": ["kubernetes", "k8s"],
    "CI/CD": ["ci/cd", "github actions", "gitlab ci", "jenkins"],
    "Stripe": ["stripe", "payment gateway", "paypal integration"],
    "Supabase": ["supabase"],
    "Celery": ["celery", "rq", "background jobs"],
    "WebSockets": ["websocket", "websockets", "socket.io", "real-time"],
    "Testing": ["unit tests", "jest", "pytest", "playwright", "cypress", "testing"],
    # --- Data analysis
    "SQL": ["sql", "t-sql", "pl/sql", "sql queries"],
    "Excel": ["excel", "spreadsheet", "spreadsheets", "vba", "google sheets", "pivot table", "pivot tables"],
    "Power BI": ["power bi", "powerbi", "dax", "power query"],
    "Tableau": ["tableau"],
    "Looker": ["looker", "looker studio", "data studio"],
    "pandas": ["pandas", "numpy", "jupyter"],
    "dbt": ["dbt"],
    "Snowflake": ["snowflake"],
    "Airflow": ["airflow", "dagster", "prefect"],
    "ETL": ["etl", "elt", "data pipeline", "data pipelines", "data warehouse", "data engineering"],
    "Statistics": ["statistics", "statistical analysis", "a/b test", "a/b testing", "hypothesis testing", "regression analysis"],
    "Data Visualization": ["data visualization", "dashboard", "dashboards", "matplotlib", "plotly", "seaborn"],
    "Google Analytics": ["google analytics", "ga4", "google tag manager", "gtm"],
    "R": ["r programming", "rstudio", "tidyverse", "ggplot"],
    # --- other domains (personas mostly should skip)
    "Mobile": ["ios", "android", "flutter", "react native", "swift", "kotlin"],
    "UI/UX Design": ["figma", "ui/ux", "ux design", "ui design", "wireframe", "prototype", "adobe xd"],
    "Graphic Design": ["logo", "photoshop", "illustrator", "graphic design", "branding", "canva"],
    "Video Editing": ["video editing", "premiere", "after effects", "capcut", "youtube editing"],
    "Copywriting": ["copywriting", "content writing", "blog post", "seo writing", "ghostwriting", "article writing"],
    "SEO": ["seo", "search engine optimization", "backlinks"],
    "Social Media": ["social media", "instagram", "tiktok", "facebook ads", "meta ads"],
    "Lead Generation": ["lead generation", "cold email", "appointment setting", "cold calling"],
    "Virtual Assistant": ["virtual assistant", "data entry", "admin support", "customer service"],
    "Blockchain": ["blockchain", "solidity", "smart contract", "web3", "nft"],
}

CATEGORY_SKILLS = {
    "ai_ml": {"PyTorch", "TensorFlow", "scikit-learn", "XGBoost", "LLM", "RAG", "LangChain", "Vector DB",
              "NLP", "Computer Vision", "Hugging Face", "Fine-tuning", "MLOps", "Time Series",
              "Recommendation Systems", "Chatbot", "Speech"},
    "web_dev": {"JavaScript", "TypeScript", "React", "Next.js", "Vue", "Angular", "Node.js", "Django",
                "FastAPI", "Flask", "PHP", "WordPress", "Shopify", "PostgreSQL", "MySQL", "MongoDB",
                "GraphQL", "REST API", "Tailwind CSS", "HTML/CSS", "Stripe", "Supabase", "WebSockets"},
    "data_analysis": {"SQL", "Excel", "Power BI", "Tableau", "Looker", "pandas", "dbt", "Snowflake",
                      "Airflow", "ETL", "Statistics", "Data Visualization", "Google Analytics", "R"},
    "mobile": {"Mobile"},
    "design": {"UI/UX Design", "Graphic Design", "Video Editing"},
    "writing": {"Copywriting"},
    "marketing": {"SEO", "Social Media", "Lead Generation"},
}

CATEGORY_KEYWORDS = {
    "ai_ml": ["machine learning", " ml ", "ai ", "artificial intelligence", "deep learning", "llm", "gpt",
              "chatbot", "nlp", "computer vision", "data scientist", "data science", "neural", "rag",
              "langchain", "model training", "ai agent", "openai"],
    "web_dev": ["web developer", "website", "web app", "full stack", "full-stack", "frontend", "front-end",
                "backend", "back-end", "react", "next.js", "node", "django", "wordpress", "shopify", "laravel",
                "saas", "landing page", "web application"],
    "data_analysis": ["data analyst", "data analysis", "dashboard", "power bi", "tableau", "excel", "sql",
                      "analytics", "reporting", "looker", "spreadsheet", "kpi", "bi developer", "data entry"],
    "mobile": ["ios", "android", "flutter", "react native", "mobile app"],
    "design": ["logo", "graphic", "figma", "ui/ux", "designer", "video edit", "illustrat", "thumbnail"],
    "writing": ["writer", "writing", "copywrit", "blog", "article", "ghostwrit", "translation", "proofread"],
    "marketing": ["marketing", "seo", "social media", "ads manager", "lead generation", "facebook ads",
                  "google ads", "appointment setter", "cold call", "sales"],
}


@cache
def _alias_regex() -> tuple[re.Pattern[str], dict[str, str]]:
    """One combined alternation (longest aliases first) -> much faster than one regex per skill."""
    alias_to_canon: dict[str, str] = {}
    for canon, aliases in SKILLS.items():
        for a in aliases + [canon.lower()]:
            alias_to_canon.setdefault(a.lower(), canon)
    alts = "|".join(re.escape(a) for a in sorted(alias_to_canon, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alts})(?![a-z0-9])", re.I), alias_to_canon


def extract_skills(text: object) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    pat, amap = _alias_regex()
    found = {amap[m.group(0).lower()] for m in pat.finditer(text) if m.group(0).lower() in amap}
    return sorted(found)


def canonical_skill(name: str) -> str | None:
    n = name.strip().lower()
    for canon, aliases in SKILLS.items():
        if n == canon.lower() or n in aliases:
            return canon
    return None


def categorize(title: object, description: object = "", skills: list[str] | None = None) -> str:
    title = title if isinstance(title, str) else ""
    description = description if isinstance(description, str) else ""
    text = f" {title} {description[:600]} ".lower()
    scores = {c: 0.0 for c in CATEGORY_KEYWORDS}
    for cat, kws in CATEGORY_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[cat] += 2.0 if kw in f" {title.lower()} " else 1.0
    for s in skills or []:
        for cat, cs in CATEGORY_SKILLS.items():
            if s in cs:
                scores[cat] += 0.75
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] >= 1.5 else "other"
