# Cachy Music Bot

Discord music bot jalan di **GitHub Actions**. Gak perlu VPS.

## Setup

### 1. Upload ke GitHub

Upload isi folder `BOT/` ke repo private GitHub.

### 2. Tambah secrets

GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | Value |
|--------|-------|
| `DISCORD_TOKEN` | Token bot Discord |
| `YT_COOKIES` | *(opsional)* Cookies YouTube base64 — kalo kena error "Sign in to confirm" |

**Cara dapetin cookies (tanpa addon):**

Di terminal PC/laptop (udah login YouTube di browser):
```bash
# Chrome
yt-dlp --cookies-from-browser chrome --cookies cookies.txt

# Firefox
yt-dlp --cookies-from-browser firefox --cookies cookies.txt
```

Encode ke base64:
```bash
base64 -w0 cookies.txt
```
Copy outputnya → paste ke secret `YT_COOKIES` di GitHub.

### 3. Jalankan

- Tab **Actions** → **Cachy Music Bot** → **Run workflow**
- Bot online di Discord

> Status Action akan "running" terus selagi bot hidup. Itu normal.

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

