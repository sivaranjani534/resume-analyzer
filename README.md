# AI-Powered Resume Analyzer

Upload a resume, paste a job description, and get a match score, matched/missing skills and improvement suggestions.
**Version 2** adds user accounts (register / login / **logout**), a progress dashboard, analysis comparison and data export.

## Features

### Core analysis
- **Resume upload** - PDF, DOCX, TXT (or paste text). Files are read in memory and never saved.
- **Skill extraction** - ~95 skills across 8 categories with aliases (e.g. `js` -> JavaScript).
- **Job matching** - overall score = 70% weighted skill match + 30% keyword (TF-IDF-style cosine) similarity.
- **Missing skills** with a concrete tip for each gap, and **prioritised suggestions** (High / Medium / Low).
- **Resume quality (ATS) score** - checklist of 14 checks.
- **Optional AI recruiter review** using the Anthropic API.

### New in v2
| Module | What it does |
|---|---|
| **Authentication** (`auth.py`) | Register, login and **logout**. Passwords are hashed; 5-attempt login throttle; safe `next` redirects; session reset on login/logout. |
| **Private history** | Every analysis belongs to its owner. Other users get a 404 for your results. |
| **Dashboard** (`/dashboard`) | Total analyses, average/best match, average quality, score-trend chart, the skills you miss most often and your strongest matches. |
| **Compare** (`/compare`) | Tick two analyses in History to see score changes, skills gained/lost and skills still missing. |
| **Search** | Filter history by job title or file name. |
| **Export** | Per analysis: TXT report and JSON. History: CSV (spreadsheet-safe). |
| **Account page** (`/account`) | Change password, export data, delete account and all analyses. |
| **Security basics** | CSRF token on every POST, auto-generated secret key, HttpOnly + SameSite cookies, `no-store` on private pages. |

## Run
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000, **register** an account, then click **Load sample data** to try it instantly.
Use the **Logout** button in the top-right of the navigation bar to sign out.

The first account you create adopts any analyses saved by the older no-login version, so you don't lose old history.

## Configuration (environment variables, all optional)
| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Session signing key. If unset, a random one is generated once and saved to `.secret_key`. Set it explicitly in production. |
| `DATABASE_PATH` | Location of the SQLite file (default `analyzer.db`). |
| `FLASK_DEBUG=1` | Enable debug mode (off by default). |
| `ANTHROPIC_API_KEY` / `AI_MODEL` | Enable the optional AI review (`pip install anthropic`). Only then is resume text sent to the API. |

Windows CMD example: `set ANTHROPIC_API_KEY=your_key` (PowerShell: `$env:ANTHROPIC_API_KEY="your_key"`).

## Structure
```
app.py          app setup, CSRF, analysis / history routes
auth.py         register, login, logout, login_required
features.py     dashboard, compare, exports, account settings
db.py           SQLite connection + schema + migration
analyzer.py     extraction, skills, scoring, suggestions, optional AI
templates/      HTML pages        static/style.css   styling
samples/        sample resume + job description
```

## Routes
`/login` `/register` `/logout` (POST) · `/` · `/analyze` · `/analysis/<id>` · `/history` · `/dashboard` · `/compare?ids=1&ids=2` ·
`/analysis/<id>/export.txt|json` · `/history/export.csv` · `/account` · `/account/delete`


## Extend it
Add skills to `SKILL_DB` in `analyzer.py`; tune weights in `analyze()`. Scanned (image) PDFs need OCR (e.g. pytesseract) - not included.
Ideas for next steps: email password reset, a cover-letter generator, an admin panel, deployment with `gunicorn`.

## Production notes
Run behind HTTPS with a real WSGI server (e.g. `gunicorn app:app`), set `SECRET_KEY`, set `SESSION_COOKIE_SECURE=True`, and use a shared store (e.g. Redis) if you run multiple workers, since the login throttle is in-memory.
