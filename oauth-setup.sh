#!/usr/bin/env bash
set -euo pipefail

LAVALINK_JAR="Lavalink.jar"
LAVALINK_URL="https://github.com/lavalink-devs/Lavalink/releases/download/4.2.2/Lavalink.jar"

if [ ! -f "$LAVALINK_JAR" ]; then
  echo "Downloading Lavalink..."
  curl -sL "$LAVALINK_URL" -o "$LAVALINK_JAR"
fi

cat > application.yml <<'YAML'
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

echo "Starting Lavalink..."
echo "When OAuth URL appears, open it in browser, login, enter code."
echo ""

java -jar "$LAVALINK_JAR"
