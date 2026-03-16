# JobBot

JobBot is a local job application workspace.

It helps you:
- save jobs you want to apply for
- score how well a job matches your profile
- generate cover letters through n8n
- track pending and applied jobs
- read job emails with local Ollama
- back up your data to an external drive

## Stack

- Streamlit for the UI
- PostgreSQL + pgvector for storage and semantic search
- n8n for the cover letter pipeline
- Gemini for extraction
- Ollama for local email analysis
- Docker Compose for local setup

## What is in Git and what stays local

This repo is safe for a public GitHub push.

These stay local and are ignored by git:
- `.env`
- `secrets/`
- `files/`
- `n8n/` exports
- personal assets like `assets/signature.png`
- local screenshots and temp files

## Quick Start

1. Clone the repo.
2. Copy `.env.example` to `.env` and fill in your values.
3. Put your Gmail OAuth file at `secrets/credentials.json` if you want the inbox page.
4. Add your own resume text at `files/master_resume.txt`.
5. Review `templates/cover_letter_template.tex` and replace the placeholder contact details with your own.
6. Start the stack:

```powershell
docker compose up -d --build
```

7. Open:

```text
http://localhost:8501
```

## Main Pages

- `New Application` for paste, screenshot, or manual entry
- `Application Pipeline` for saved jobs and applied jobs
- `Application Dashboard` for funnel and activity charts
- `Job Email Inbox` for Gmail + Ollama analysis
- `Backup & Recovery` for backup status and restore notes

## n8n

The public repo does not include your live n8n workflow exports.
Keep those local in the `n8n/` folder if you want them backed up.

## Backup

Manual backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup_jobbot.ps1
```

Register the automatic Windows task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_backup_task.ps1
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

## Remote Access with Tailscale

Keep the Docker ports bound to `127.0.0.1`.
Then use Tailscale Serve on the host machine:

```powershell
tailscale serve --bg 8501
```

After that, open the Tailscale URL from your own devices signed into the same tailnet.

## Notes

- This repo starts clean, but some features need your own local secrets and files.
- If you already have live data, do not delete `files/`, `secrets/`, `.env`, or your local `n8n/` folder.
- If you change Streamlit code, rebuild the container:

```powershell
docker compose up -d --build --force-recreate streamlit
```
