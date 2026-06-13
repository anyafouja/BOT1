# Cachy Music Bot

Discord music bot jalan di **GitHub Actions**. Gak perlu VPS.

## Setup

### 1. Upload ke GitHub

Bikin repo private baru di GitHub, lalu:

```bash
git clone https://github.com/USER/REPO.git
# copy semua isi folder BOT ke dalam repo
cp -r BOT/* .
cp -r BOT/.* .
git add .
git commit -m "init"
git push
```

Atau upload manual lewat web GitHub (drag & drop isi folder BOT).

### 2. Tambah token

- GitHub repo → **Settings** → **Secrets and variables** → **Actions**
- New secret: `DISCORD_TOKEN` → isi token bot

### 3. Jalankan

- Tab **Actions** → **Cachy Music Bot** → **Run workflow**
- Bot online di Discord

## Commands

Prefix: `cachy `

| Perintah | Fungsi |
|----------|--------|
| `cachy play <judul>` | Putar lagu |
| `cachy skip` | Skip |
| `cachy stop` | Stop |
| `cachy pause/resume` | Pause/Resume |
| `cachy queue` | Antrian |
| `cachy volume 50` | Volume |
| `cachy loop` | Loop |
| `cachy shuffle` | Acak |
| `cachy clear-queue` | Kosongin |
| `cachy ping` | Cek bot |
