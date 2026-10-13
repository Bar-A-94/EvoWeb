#!/usr/bin/env bash
# Setup an Ubuntu instance for WebGen-Bench evaluation.
# Installs: Node.js, pm2, Python 3, pip, Google Chrome + chromedriver.
#
# Usage (bare metal):   sudo bash setup_instance.sh
# Usage (Dockerfile):   RUN bash setup_instance.sh

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== System packages ==="
apt-get update
apt-get install -y --no-install-recommends \
    curl wget git unzip ca-certificates gnupg \
    python3 python3-pip python3-venv \
    fonts-liberation xdg-utils

echo "=== Google Chrome (stable) ==="
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get install -y /tmp/chrome.deb || apt-get install -fy
rm /tmp/chrome.deb
CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+')
echo "Chrome: $CHROME_VERSION"

echo "=== Chromedriver (matching version) ==="
CHROME_MAJOR=$(echo "$CHROME_VERSION" | cut -d. -f1)
CD_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}.0/linux64/chromedriver-linux64.zip"
# Try exact match first, fall back to latest for this major version
wget -q -O /tmp/chromedriver.zip "$CD_URL" 2>/dev/null || {
    # Use Chrome for Testing JSON endpoint to find the right version
    CD_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_MAJOR}" | xargs -I{} echo "https://storage.googleapis.com/chrome-for-testing-public/{}/linux64/chromedriver-linux64.zip")
    wget -q -O /tmp/chromedriver.zip "$CD_URL"
}
cd /tmp && unzip -q chromedriver.zip && mv chromedriver-linux64/chromedriver /usr/bin/chromedriver && chmod +x /usr/bin/chromedriver
rm -rf /tmp/chromedriver*
echo "Chromedriver: $(chromedriver --version)"

echo "=== Node.js 22 ==="
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs
echo "Node: $(node --version)"

echo "=== pm2 ==="
npm install -g pm2

echo "=== Python packages ==="
# The judge (webvoyager/) and the worker: SDKs, Selenium, awscli for the opt-in S3 path.
pip3 install --no-cache-dir \
    openai>=1.1.1 \
    anthropic>=0.75.0 \
    selenium>=4.15.2 \
    pillow>=10.1.0 \
    tqdm numpy boto3 awscli \
    fastapi uvicorn httpx

echo "=== Cleanup ==="
apt-get clean && rm -rf /var/lib/apt/lists/*

echo "=== Done ==="
echo "Chrome:       $(google-chrome --version)"
echo "Chromedriver: $(chromedriver --version)"
echo "Node:         $(node --version)"
echo "Python:       $(python3 --version)"

echo "=== uv ==="
# The ACP coding-agent generators start their client with `uv run --script`.
curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
echo "uv: $(uv --version)"
