# JobBot

JobBot is a local workspace for job search, cover letters, applications, and follow-ups.

It gives you one place to:
- save jobs you want to apply for
- check how well a job matches your profile
- generate cover letters through n8n
- upload your own cover letter, resume, and extra files
- track pending and applied jobs
- review job emails with local Ollama
- back up your data to an external drive

## Stack

- Streamlit for the UI
- PostgreSQL + pgvector for storage and semantic search
- n8n for the cover-letter pipeline
- Gemini for extraction
- Vertex AI for the main Generator / Critic / Refiner loop
- Ollama for local email analysis
- Docker Compose for local setup

## Pipeline Overview

![JobBot n8n Pipeline](docs/n8n-pipeline.svg)

## Quick Start

1. Clone the repo.
2. Copy `.env.example` to `.env` and fill in your values.
3. Put your Gmail OAuth client at `secrets/credentials.json` if you want the inbox page.
4. Add your resume text at `files/master_resume.txt`.
5. If you want your own contact block and signature in the final letter, copy `templates/cover_letter_template.tex` to `templates/cover_letter_template.local.tex` and edit the local file.
6. Start the stack:

```powershell
docker compose up -d --build
```

7. Open the app:

```text
http://localhost:8501
```

## Main Pages

- `New Application` for paste, screenshot, or manual entry
- `Application Pipeline` for saved jobs and applied jobs
- `Application Dashboard` for funnel and activity charts
- `Job Email Inbox` for Gmail + Ollama analysis
- `Backup & Recovery` for backup status and restore notes

## Backup

Manual backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scriptsackup_jobbot.ps1
```

Register the automatic Windows task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts
egister_backup_task.ps1
```

Backups are written to:

```text
F:\jobbot_backup\current
```

The backup includes:
- database dump
- `files/`
- `secrets/`
- `.env`
- local `n8n/` exports

## Remote Access

Keep the Docker ports bound to `127.0.0.1`.
Then use Tailscale Serve on the host machine:

```powershell
tailscale serve --bg 8501
```

Then open the Tailscale URL from your own devices on the same tailnet.

## Notes

- The public repo does not include your live n8n export or credentials.
- If you already have live data, do not delete `files/`, `secrets/`, `.env`, or your local `n8n/` folder.
- If you change Streamlit code, rebuild the container:

```powershell
docker compose up -d --build --force-recreate streamlit
```
