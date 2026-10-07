"""
AI Lead Research Agent
======================
Turns a plain list of companies into researched, scored, ready-to-send outreach.

For each company in leads.csv it:
  1. Visits the company's website (homepage + about page), respecting robots.txt
  2. Asks Claude to work out: what they do, their likely pain point,
     how well they fit YOUR offer (score 1-10) and why
  3. Drafts a short, personalised cold email based on what it actually found
  4. Saves everything to results.csv + a readable report.md, best leads first

Works for any business: SaaS sales, B2B services, export/import, recruiting...
You only change offer.txt (what you sell) and leads.csv (who to research).

Three AI options — two are FREE:
    gemini  (default, FREE)  Google Gemini free tier. Free key at aistudio.google.com
    ollama  (FREE, offline)  Runs an open-source model on your own computer
    claude  (paid)           Anthropic Claude API

Usage:
    pip install -r requirements.txt
    export GEMINI_API_KEY="your-free-key"      (Windows: set GEMINI_API_KEY=...)
    python lead_agent.py                       # free run with Gemini
    python lead_agent.py --provider ollama     # free, fully on your computer
    python lead_agent.py --demo                # offline demo, no key needed
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# Free Gemini tier allows only ~10 requests per minute, so wait between companies
DELAY = {"gemini": 7, "ollama": 1, "claude": 2}
USER_AGENT = "LeadResearchAgent/1.0 (personal research tool)"
MAX_CHARS_PER_PAGE = 6000     # keeps each API call small and cheap
ABOUT_PATHS = ["/about", "/about-us", "/company", "/a-propos", "/qui-sommes-nous"]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — READ WEBSITES
# ─────────────────────────────────────────────────────────────────────────────
def allowed_by_robots(url: str) -> bool:
    """Only read pages the website allows bots to read."""
    parts = urlparse(url)
    rp = robotparser.RobotFileParser()
    rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True  # no robots.txt reachable -> treat as allowed


def page_text(url: str) -> str:
    """Download a page and return its visible text."""
    if not allowed_by_robots(url):
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            return ""
    except requests.RequestException:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text[:MAX_CHARS_PER_PAGE]


def research_company(website: str) -> str:
    """Homepage + first about-page that exists."""
    if not website.startswith("http"):
        website = "https://" + website
    home = page_text(website)
    about = ""
    for path in ABOUT_PATHS:
        about = page_text(urljoin(website, path))
        if len(about) > 300:
            break
    return f"HOMEPAGE:\n{home}\n\nABOUT PAGE:\n{about}".strip()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 + 3 — ANALYSE AND DRAFT WITH CLAUDE
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a sharp B2B sales researcher.
You get (a) a description of what the sender offers and (b) text scraped from a
prospect's website. Use ONLY facts from the website text. Never invent numbers,
customers, people's names or news. If the website text is empty or unclear,
say so and give fit_score 0.

Reply with ONLY a JSON object, no markdown, with exactly these keys:
{
  "what_they_do": "one plain sentence",
  "likely_pain": "the most relevant problem the sender could solve for them, one sentence",
  "fit_score": integer 0-10,
  "fit_reason": "one sentence explaining the score",
  "email_subject": "under 8 words, specific, no clickbait",
  "email_body": "under 90 words, mentions one specific thing from their site, one clear ask, friendly and human, no buzzwords, sign as {sender_name}"
}"""


def build_prompt(offer, company, site_text):
    return f"WHAT I OFFER:\n{offer}\n\nPROSPECT: {company}\n\nWEBSITE TEXT:\n{site_text or '(empty)'}"


GEMINI_PREFERRED = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite",
                    "gemini-flash-lite-latest", "gemini-2.0-flash"]
_gemini_models_cache = []
_gemini_auth = {}


def _gemini_headers() -> dict:
    if not _gemini_auth:
        _gemini_auth.update({"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(),
                             "Content-Type": "application/json"})
    return _gemini_auth


def google_error(r) -> str:
    """Extract Google's own error message so the user sees the real reason."""
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:200]


def gemini_models(headers) -> list:
    """Ask Google which models this key can use, best free Flash models first."""
    if _gemini_models_cache:
        return _gemini_models_cache
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
    r = requests.get(url, headers=headers, timeout=60)
    if r.status_code in (400, 401, 403):
        # New AI Studio keys start with "AQ." — try sending them as a Bearer token
        key = headers.pop("x-goog-api-key")
        headers["Authorization"] = f"Bearer {key}"
        r2 = requests.get(url, headers=headers, timeout=60)
        if r2.status_code == 200:
            r = r2
        else:
            headers.pop("Authorization")
            headers["x-goog-api-key"] = key
    if r.status_code != 200:
        raise RuntimeError(f"Google rejected the key: {google_error(r)}")
    names = [m["name"].replace("models/", "") for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and "image" not in n and "tts" not in n
             and "live" not in n and "audio" not in n]
    ordered = [m for m in GEMINI_PREFERRED if m in names]
    ordered += [m for m in sorted(flash, reverse=True) if m not in ordered]
    if GEMINI_MODEL in names and GEMINI_MODEL not in ordered:
        ordered.insert(0, GEMINI_MODEL)
    if not ordered:
        raise RuntimeError("Your key works but no Gemini Flash model is available to it.")
    _gemini_models_cache.extend(ordered[:4])
    return _gemini_models_cache


def ask_gemini(system: str, prompt: str) -> str:
    """Google Gemini free tier. Retries when busy and falls back to other available models."""
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    headers = _gemini_headers()
    last_error = "unknown"
    for model in gemini_models(headers):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=120)
            except requests.RequestException:
                last_error = "slow or broken internet connection"
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 200:
                try:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    last_error = "empty answer from Gemini"
                    break
            if r.status_code in (429, 500, 503):
                last_error = f"{model}: {google_error(r)}"
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code in (401, 403) or "API key" in google_error(r):
                raise RuntimeError(f"Key problem: {google_error(r)}")
            last_error = f"{model}: {google_error(r)}"
            break
    raise RuntimeError(last_error)


def ask_ollama(system: str, prompt: str) -> str:
    """Local open-source model via Ollama (free, nothing leaves your computer)."""
    r = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
        "model": OLLAMA_MODEL,
        "format": "json",
        "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
    })
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:200]} (is Ollama running?)")
    return r.json()["message"]["content"]


def ask_claude(system: str, prompt: str) -> str:
    import anthropic  # only needed for the paid option
    msg = anthropic.Anthropic().messages.create(
        model=CLAUDE_MODEL, max_tokens=800, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


PROVIDERS = {"gemini": ask_gemini, "ollama": ask_ollama, "claude": ask_claude}
KEY_NEEDED = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def analyse(provider, offer, company, site_text, sender_name) -> dict:
    system = SYSTEM_PROMPT.replace("{sender_name}", sender_name)
    raw = PROVIDERS[provider](system, build_prompt(offer, company, site_text))
    return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Pull the JSON object out of the model's reply, even if wrapped in ``` fences."""
    raw = re.sub(r"```(json)?", "", raw).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("No JSON found in reply")
    data = json.loads(match.group(0))
    data["fit_score"] = int(data.get("fit_score", 0))
    return data


def demo_analysis(company: str) -> dict:
    """Fake but realistic output so you can test the pipeline with no API key."""
    return {
        "what_they_do": f"{company} sells software to small businesses (demo data).",
        "likely_pain": "Their team likely spends hours on manual prospect research (demo data).",
        "fit_score": (len(company) * 3) % 11,
        "fit_reason": "Demo mode: score is not real.",
        "email_subject": f"Quick idea for {company}",
        "email_body": f"Hi {company} team, this is a demo email generated without the API. Run without --demo for real drafts.",
    }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — SAVE RESULTS
# ─────────────────────────────────────────────────────────────────────────────
FIELDS = ["company", "website", "fit_score", "what_they_do", "likely_pain",
          "fit_reason", "email_subject", "email_body", "status"]


def save(results: list, out_csv: str, out_md: str):
    results.sort(key=lambda r: r.get("fit_score", 0), reverse=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# Lead research report\n\nSorted by fit score (best first).\n\n")
        for r in results:
            f.write(f"## {r['company']} — fit {r.get('fit_score', 0)}/10\n\n")
            f.write(f"**What they do:** {r.get('what_they_do', '')}\n\n")
            f.write(f"**Likely pain:** {r.get('likely_pain', '')}\n\n")
            f.write(f"**Why this score:** {r.get('fit_reason', '')}\n\n")
            f.write(f"**Subject:** {r.get('email_subject', '')}\n\n")
            f.write(f"{r.get('email_body', '')}\n\n---\n\n")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="AI Lead Research Agent")
    ap.add_argument("--leads", default="leads.csv", help="CSV with columns: company,website")
    ap.add_argument("--offer", default="offer.txt", help="Text file describing what you sell")
    ap.add_argument("--sender", default="Naishal", help="Name to sign emails with")
    ap.add_argument("--out", default="results", help="Output file name (no extension)")
    ap.add_argument("--provider", default="gemini", choices=list(PROVIDERS),
                    help="gemini (free, default) | ollama (free, local) | claude (paid)")
    ap.add_argument("--demo", action="store_true", help="Offline demo: no web, no API key")
    args = ap.parse_args()

    key = KEY_NEEDED.get(args.provider)
    if not args.demo and key and not os.environ.get(key):
        sys.exit(f"Set {key} first (see README), or run with --demo to test.")

    offer = open(args.offer, encoding="utf-8").read().strip()
    with open(args.leads, newline="", encoding="utf-8") as f:
        leads = [row for row in csv.DictReader(f) if row.get("company")]

    print(f"Researching {len(leads)} companies with {'demo' if args.demo else args.provider}...\n")
    results = []
    for i, lead in enumerate(leads, 1):
        company, website = lead["company"].strip(), lead.get("website", "").strip()
        print(f"[{i}/{len(leads)}] {company}", end=" ... ", flush=True)
        row = {"company": company, "website": website}
        try:
            if args.demo:
                analysis = demo_analysis(company)
            else:
                site_text = research_company(website) if website else ""
                analysis = analyse(args.provider, offer, company, site_text, args.sender)
                time.sleep(DELAY[args.provider])
            row.update(analysis)
            row["status"] = "ok"
            print(f"fit {row['fit_score']}/10")
        except Exception as e:
            row.update({"fit_score": 0, "status": f"error: {e}"})
            print(f"error ({e})")
        results.append(row)

    save(results, f"{args.out}.csv", f"{args.out}.md")
    good = sum(1 for r in results if r.get("fit_score", 0) >= 7)
    print(f"\nDone. {good} strong leads (7+/10). Saved {args.out}.csv and {args.out}.md")


if __name__ == "__main__":
    main()
