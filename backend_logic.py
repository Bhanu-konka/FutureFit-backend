import os
import pandas as pd
import requests
import google.generativeai as genai
import PyPDF2
from typing import List, Dict, Optional

# --- API Keys (prefer env vars; no secrets in code) ---
SERP_API_KEY = os.getenv("SERPAPI_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GOOGLE_JOBS_ENDPOINT = "https://serpapi.com/search.json"


def _pick_best_apply_link(job: Dict) -> str:
    """
    Choose the best apply link from SerpApi's apply_options.
    Heuristics: prefer company/careers/ATS domains; else first option; else share_link; else '#'.
    """
    apply_options = job.get("apply_options", []) or []
    company = (job.get("company_name") or "").lower()

    if apply_options:
        def score(opt: Dict) -> int:
            link = (opt.get("link") or "").lower()
            s = 0
            if company and company in link:
                s += 5
            for kw in ["careers", "jobs.", "workday", "greenhouse", "lever",
                       "smartrecruiters", "successfactors", "myworkdayjobs",
                       "oraclecloud", "adp", "ashby", "icims", "bamboohr"]:
                if kw in link:
                    s += 3
            for bad in ["indeed.", "linkedin.", "ziprecruiter.", "talent.com",
                        "glassdoor.", "bebee.", "naukri.", "monster."]:
                if bad in link:
                    s -= 1
            return s

        best = sorted(apply_options, key=score, reverse=True)[0]
        if best.get("link"):
            return best["link"]

    if job.get("share_link"):
        return job["share_link"]
    return "#"


def run_scraper_logic(job_title: str, location: str) -> bool:
    """
    Scrapes jobs from SerpApi (with apply links) for a specific location and saves them to CSV.
    """
    if not SERP_API_KEY:
        print("SERPAPI_KEY not set")
        return False

    print(f"Starting scraper for: '{job_title}' in '{location}'")
    all_jobs: List[Dict] = []

    params = {
        "engine": "google_jobs",
        "q": f"fresher {job_title} in {location}",
        "location": location,
        "api_key": SERP_API_KEY,
        "hl": "en",
    }

    try:
        resp = requests.get(GOOGLE_JOBS_ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "jobs_results" in data and data["jobs_results"]:
            all_jobs.extend(data["jobs_results"])
    except Exception as e:
        print(f"Scraper Error for location {location}: {e}")
        return False

    if not all_jobs:
        print("Scraper found no jobs in this domain/location.")
        return False

    # Normalize + de-duplicate by job_id (fallback to title+company+location)
    seen = set()
    processed = []
    for job in all_jobs:
        job_id = job.get("job_id") or ""
        key = job_id or f"{job.get('title')}|{job.get('company_name')}|{job.get('location')}"
        if key in seen:
            continue
        seen.add(key)

        processed.append({
            "source": job.get("via", "Google Jobs"),
            "title": job.get("title", "N/A"),
            "company": job.get("company_name", "N/A"),
            "job_id": job_id,
            "location": job.get("location", "N/A"),
            "description": job.get("description", "N/A"),
            "share_link": job.get("share_link", ""),
            "apply_link": _pick_best_apply_link(job),
        })

    pd.DataFrame(processed).to_csv("scraped_jobs.csv", index=False)
    print(f"Scraper finished. Saved {len(processed)} jobs to scraped_jobs.csv")
    return True


def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
            return "\n".join(text_parts).strip()
    except Exception as e:
        print(f"PDF reading error: {e}")
        return None


def run_analyzer_logic(resume_path: str, jobs_csv_path: str) -> List[Dict]:
    """Generates tailored cover letters and returns jobs + links."""
    print("Starting analyzer...")

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set")
        return []

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
    except Exception as e:
        print(f"Gemini configuration error: {e}")
        return []

    resume_text = extract_text_from_pdf(resume_path)
    if not resume_text:
        return []

    try:
        jobs_df = pd.read_csv(jobs_csv_path)
    except FileNotFoundError:
        print("Analyzer could not find scraped_jobs.csv")
        return []

    matched_jobs: List[Dict] = []

    for idx, job in jobs_df.head(5).iterrows():
        print(f"Analyzing job {idx + 1}/{len(jobs_df.head(5))}: {job['title']}...")

        prompt = f"""
Act as an expert HR assistant. Your tasks are:
1) Generate a short, professional, tailored cover letter (~100–150 words) that highlights the key skills from the resume relevant to the job description for the "{job['title']}" role at "{job['company']}".
2) Conclude with a professional closing like 'Sincerely,' followed by the applicant's full name. Extract the name from the top of the RESUME TEXT.

RESUME TEXT:
{resume_text}

JOB DESCRIPTION:
{job.get('description','')}
"""
        try:
            response = model.generate_content(prompt)
            cover = (getattr(response, "text", "") or "").strip()

            apply_link = job.get("apply_link") or ""
            if not apply_link or apply_link == "#":
                if isinstance(job.get("share_link"), str) and job["share_link"]:
                    apply_link = job["share_link"]
                elif isinstance(job.get("job_id"), str) and job["job_id"]:
                    jid = job["job_id"]
                    apply_link = f"https://www.google.com/search?q=jobs&ibp=htl;jobs#htivrt=jobs&htidocid={jid}"
                else:
                    apply_link = "#"

            matched_jobs.append({
                "company": job["company"],
                "title": job["title"],
                "location": job.get("location", ""),
                "link": apply_link,
                "cover_letter": cover
            })
            print(f"  -> Cover letter generated for {job['company']}.")
        except Exception as e:
            print(f"Gemini API call failed for {job.get('company','N/A')}: {e}")
            continue

    print(f"Analyzer finished. Found {len(matched_jobs)} matches.")
    return matched_jobs
