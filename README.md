# AI Lead Research Agent

**The problem:** salespeople, founders and job seekers spend most of their outreach time on research, not on talking to people. Open a website, figure out what the company does, guess if they're a fit, write a personal email. Repeat 50 times. When people skip the research, they send generic AI emails that everyone ignores.

**What this does:** you give it a list of companies and a description of what you offer. For each company it:

1. Reads their website (homepage + about page), respecting robots.txt
2. Works out what they do and their most likely pain point
3. Scores how well they fit your offer, from 0 to 10, with a reason
4. Drafts a short email that mentions something real from their site

You get `results.csv` (open in Excel) and `results.md` (readable report), best leads first.

It only uses facts found on the website. It is told never to invent numbers, customers or names. **Always read and edit each email before sending.**

---

## Setup — 100% free (about 5 minutes)

You can choose between two free AI options.

### Option A: Google Gemini free tier (easiest, recommended)

**Step 1. Install the packages**
```bash
pip install -r requirements.txt
```

**Step 2. Get a free API key**
Go to https://aistudio.google.com, sign in with your Google account, and click **Get API key**. No credit card needed.

**Step 3. Add the key to your terminal**
```bash
export GEMINI_API_KEY="your-key"        # Mac / Linux
set GEMINI_API_KEY=your-key             # Windows
```
Never paste your key into the code or upload it to GitHub.

**Step 4. Run it**
```bash
python lead_agent.py
```

Free tier notes:
- It is rate-limited (only a few requests per minute and a daily cap). The script waits between companies and retries automatically, so 20 companies take a few minutes.
- On the free tier, Google may use what you send to improve its models. That is fine for public website text, but never send private customer data.
- If you see a "model not found" error, check the current free Flash model name in AI Studio and run, for example: `export GEMINI_MODEL="gemini-2.5-flash"`

### Option B: Ollama (free, runs fully on your computer, no key)

1. Download Ollama from https://ollama.com and install it
2. In a terminal: `ollama pull llama3.2`
3. Run: `python lead_agent.py --provider ollama`

Nothing leaves your computer. It is slower and the emails are a bit weaker than Gemini, but it has no limits.

### Web app version (best for demos)
```bash
pip install streamlit
streamlit run app.py
```
Your browser opens a simple page: describe your offer, paste companies, click **Research leads**. Results, scores and editable email drafts appear on screen, with a CSV download. Choose "demo" in the sidebar to try it with no key.

### Test without any AI (optional)
```bash
python lead_agent.py --demo
```

### Paid option (later)
If you ever get a Claude API key: `export ANTHROPIC_API_KEY="..."`, `pip install anthropic`, then `python lead_agent.py --provider claude`.

---

## Use it for your own business

Change two files:

| File | What to put in it |
|---|---|
| `offer.txt` | What you sell and who your ideal customer is, in plain words |
| `leads.csv` | Two columns: `company,website` |

Example for selling Indian grocery products to Paris shops:
```bash
python lead_agent.py --offer examples/offer_india_export.txt --leads my_paris_shops.csv --out paris_shops
```

Other uses: a recruiter screening companies, an agency finding clients, a founder finding pilot customers, a student targeting startups for internships.

---

## How it works

```
leads.csv ──► read website ──► AI analyses ──► score + email ──► results.csv / results.md
```

- `requests` + `BeautifulSoup` download and clean the website text
- An AI model (Gemini free tier, a local Ollama model, or Claude) returns structured JSON: what they do, pain, score, reason, email
- Results sorted by score so you start with the best leads

## Responsible use

- Reads only public company websites, and skips pages blocked by robots.txt
- Waits between sites so it doesn't overload anyone's server
- Researches companies, not private individuals
- Follow anti-spam rules (e.g. GDPR in Europe): send relevant, personal emails and honour opt-outs
