# Rundown

Your Slack, caught up. Local dashboard. Channel summaries, priorities, and a calendar of past runs.

## Quick start

Need: **Python 3.11+**, a Slack user token, and **Ollama or Claude Code**.

In the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m rundown serve
```

Windows: use `python` instead of `python3`. Activate with `.venv\Scripts\Activate.ps1`.

Open **[localhost:8000](http://127.0.0.1:8000)**.

1. Paste your Slack user token.
2. Choose Ollama or Claude Code. Enter the model.
3. Leave the other defaults. Or change keywords and the summaries folder.
4. Click **Save**.
5. Connections ready? Click **Run now**.

No config file to create. Missing or incomplete config opens setup automatically.

### Get your Slack token

1. Open [Slack app management](https://api.slack.com/apps).
2. **Create New App → From a manifest**. Choose your workspace.
3. Paste [slack-manifest.json](slack-manifest.json). Create and install the app.
4. **OAuth & Permissions → User OAuth Token**. Copy the `xoxp-…` token.

Use a **user** token, not a bot token (`xoxb-`). Your workspace may need admin approval.

Default: joined public and private channels. Optional DMs need `im:read` + `im:history`. Group DMs need `mpim:read` + `mpim:history`. Add these as user scopes, then reinstall the Slack app.

### Choose one AI

**Ollama — local**

- Install and start [Ollama](https://ollama.com).
- Download a model. Run `ollama list` to see installed model names.
- In setup: choose Ollama. Paste an installed model name.
- Keep the default address: `http://127.0.0.1:11434`.

**Claude Code — your existing login**

- Install [Claude Code](https://code.claude.com/docs/en/setup).
- Run `claude auth login`.
- In setup: choose Claude Code. Defaults: executable `claude`, model `sonnet`.
- Slack text is sent through your Claude account. No separate API key needed.

## Everyday use

Start again:

```sh
source .venv/bin/activate
python -m rundown serve
```

- **Run now**: fetch and summarize new activity. Never runs automatically.
- **Date rail**: revisit old digests. Run selector for multiple runs that day.
- **Settings**: edit connections, keywords, and output paths. No restart needed.
- **Dark mode / Light mode**: top-right toggle. Remembers your choice in this browser; initially follows your system.
- **Eye button**: show/hide the token you are typing. Previously saved tokens stay hidden. Blank = keep the saved token.
- **Stop server**: Ctrl+C in the terminal.

### Developer preview

Hover just to the right of the dark-mode button to reveal **</>**, then click it. Keyboard users can Tab to it. No setup required.

Sample dashboard only. Dates, multiple runs, search, channel filters, and a partial-run example. No Slack/AI calls, config changes, or saved data. **Exit preview** returns to your previous screen, keeping any unsaved setup fields. Refreshing leaves preview mode.

## If something fails

- **Highlighted field**: correct it and save again. Invalid settings are not saved.
- **Slack connection failed**: check the user token, app installation, and permissions.
- **Ollama failed**: start Ollama. Check the model name with `ollama list`.
- **Claude Code failed**: run `claude --version` and `claude auth status`. Sign in or update if needed.
- **Settings saved, connection failed**: details are kept. Fix and save, click **Recheck saved connections**, or **Open dashboard anyway** to read history.
- **Digest running**: wait before saving settings. Only one run at a time.
- **Partial run**: successful channels are saved. Run again to retry failed channels.

## Files and privacy

- `config.toml`: local settings and token. Keep private. Browser saves replace comments.
- `data/rundown.sqlite3`: history and checkpoints. Back it up.
- `summaries/`: Markdown copies of each run.
- Changing the database path opens a separate archive; it does not move history.
- Config, database, and exports are git-ignored. Do not share them publicly.
- Full fetched messages are not stored as a raw archive. Summaries may still contain sensitive text.
- Ollama stays local. Claude Code sends selected Slack content to Claude.
- Server is local-only. No cloud hosting or shared accounts.
- First run: previous 24 hours. Later runs: new activity per channel, including other people's messages.
- Old untracked thread replies may be missed. Edits/deletions do not rewrite past summaries. Not a complete Slack backup.
- AI summaries can be wrong. Follow source links to check.

Optional: enter `env:SLACK_USER_TOKEN` instead of a literal token. Set that environment variable before starting the server. `.env` files are not loaded automatically.

## Terminal / advanced

```sh
python -m rundown check --config config.toml
python -m rundown run --config config.toml
python -m rundown serve --config config.toml --port 8000
```

[config.example.toml](config.example.toml) lists all settings. Direct file edits or environment changes need a server restart. Malformed TOML must be fixed before startup. Use a separate database for each workspace.

Tests — mocked Slack and AI; no credentials needed:

```sh
python -m pip install -e '.[test]'
python -m pytest
```

Optional preview tests (requires Node.js): `node --test tests/frontend.test.cjs`.

Python + FastAPI + SQLite. Plain HTML/CSS/JavaScript. No frontend build step.
