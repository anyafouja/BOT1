#!/usr/bin/env bash
set -euo pipefail

LAVALINK_JAR="Lavalink.jar"
LAVALINK_URL="https://github.com/lavalink-devs/Lavalink/releases/download/4.2.2/Lavalink.jar"
CONFIG_URL="https://raw.githubusercontent.com/anyafouja/CachyMusic/main/application.yml"

if [ ! -f "$LAVALINK_JAR" ]; then
  echo "Downloading Lavalink..."
  curl -sL "$LAVALINK_URL" -o "$LAVALINK_JAR"
fi

echo "Downloading full config from repo..."
curl -sL "$CONFIG_URL" > application-oauth.yml

# Patch config: enable OAuth without skipInitialization, use TV client only
python3 -c "
import yaml
with open('application-oauth.yml') as f:
    data = yaml.safe_load(f)
plugins = data.setdefault('plugins', {})
yt = plugins.setdefault('youtube', {})
yt['enabled'] = True
yt['allowSearch'] = True
yt['oauth'] = {'enabled': True}
yt['clients'] = ['TV']
with open('application-oauth.yml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False)
print('Config patched for OAuth')
"

echo ""
echo "Starting Lavalink with OAuth..."
echo "When OAuth URL appears, open it in browser, login, enter code."
echo ""

java -jar "$LAVALINK_JAR" --spring.config.additional-location=application-oauth.yml
