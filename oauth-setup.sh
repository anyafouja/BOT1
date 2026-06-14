#!/usr/bin/env bash
set -euo pipefail

echo "=== Cachy Music — YouTube OAuth Setup ==="
echo ""

LAVALINK_JAR="Lavalink.jar"
LAVALINK_URL="https://github.com/lavalink-devs/Lavalink/releases/download/4.2.2/Lavalink.jar"

# Download Lavalink if not present
if [ ! -f "$LAVALINK_JAR" ]; then
  echo "[1/4] Downloading Lavalink 4.2.2..."
  curl -sL "$LAVALINK_URL" -o "$LAVALINK_JAR"
fi

# Create temporary oauth config
cat > application-oauth.yml <<'YAML'
server:
  port: 2333
  address: 0.0.0.0
lavalink:
  plugins:
    - dependency: "dev.lavalink.youtube:youtube-plugin:1.18.1"
      snapshot: false
  server:
    password: youshallnotpass
    sources:
      youtube: false
    bufferDurationMs: 400
    playerUpdateInterval: 5
    youtubeSearchEnabled: true
plugins:
  youtube:
    enabled: true
    allowSearch: true
    oauth:
      enabled: true
    clients:
      - TV
logging:
  level:
    root: INFO
    lavalink: INFO
    dev.lavalink.youtube.http.YoutubeOauth2Handler: INFO
YAML

echo "[2/4] Starting Lavalink with OAuth enabled..."
echo ""
echo "When prompted, open the URL below in your browser, sign in with"
echo "your Google account (use a burner account!), and enter the code."
echo ""
echo "The refresh token will appear in the terminal after that."
echo "Copy it and save it somewhere."
echo ""

java -jar "$LAVALINK_JAR" --spring.config.additional-location=application-oauth.yml

echo ""
echo "=== Done ==="
