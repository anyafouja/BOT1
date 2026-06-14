# Cachy Music

Discord music bot that plays audio from SoundCloud. Runs on GitHub Actions.

## Commands
- `cachy play <query>` — Play a song from SoundCloud
- `cachy skip` — Skip current track
- `cachy stop` — Stop and disconnect
- `cachy pause / resume` — Pause/resume playback
- `cachy queue` — Show the queue
- `cachy volume <1-100>` — Set volume
- `cachy loop` — Toggle loop
- `cachy shuffle` — Shuffle the queue
- `cachy clear-queue` — Clear all queued tracks

## Setup
1. Fork this repo
2. Add `DISCORD_TOKEN` secret in GitHub Settings → Secrets and variables → Actions
3. Trigger the workflow manually or push to `main`
