FROM python:3.12-slim

# Install Chrome dependencies + Chrome + Xvfb (virtual framebuffer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    xvfb \
    xauth \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor > /usr/share/keyrings/googlechrome-linux-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Xvfb virtual display for non-headless Chrome (required for Cloudflare bypass)
ENV DISPLAY=:99

# Start Xvfb in the background, wait for it, then launch the app.
# Shell form is required to expand $PORT (assigned dynamically by hosting platforms).
CMD Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -ac &>/dev/null & sleep 2 && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
