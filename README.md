# OpenLearn

Open Learn is a local-first AI tutor. Ask about a topic, learn from your own material, take a quiz, and keep your notes on your device.

## Try it on Windows

You’ll need [Git](https://git-scm.com/download/win), [Node.js 22.13 or newer](https://nodejs.org/), and [Python 3.12 or newer](https://www.python.org/downloads/).

In PowerShell, run:

```powershell
git clone https://github.com/harshilgor/Open-Learn.git
cd Open-Learn
.\install-local.ps1
```

The script installs what Open Learn needs and starts it. 

- Then open [http://127.0.0.1:3000](http://127.0.0.1:3000).
- If you want to stop it Run `Ctrl+C` in PowerShell to stop.

API Key 

- AI access is provided by Open Learn. Customers use **Settings → AI service** to check availability; they do not supply provider keys. See `docs/PRODUCT_SERVICE_REPAIR.md` for the shared backend and client deployment configuration.

## What you can do

- Learn through a guided chat with interactive visuals.
- Ask questions about PDFs, notes, and other learning materials.
- Write and organize local study notes.
- Take quizzes and review topics later.

Your learning data stays on this device. Read the [installation guide](docs/INSTALL.md) for help, or the [release notes](CHANGELOG.md) to see what’s new.

## For contributors

See [docs/INSTALL.md](docs/INSTALL.md) for development commands. The backend uses FastAPI and SQLite; the web app uses React and TypeScript.

There is no project license yet, so reuse rights have not been granted.
