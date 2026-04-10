FROM python:3.11-slim

# ---- System dependencies ------------------------------------------------
# Playwright browser deps + virtual display stack for headed login flow
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright/Chromium runtime
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libcups2 libgtk-3-0 libx11-xcb1 \
    # Virtual framebuffer + VNC for headful login in-container
    xvfb x11vnc novnc websockify \
    && rm -rf /var/lib/apt/lists/*

# ---- Python deps --------------------------------------------------------
WORKDIR /app
COPY requirements.txt .

# Install runtime deps only (no dev tools like ruff/mypy/pytest in image)
RUN pip install --no-cache-dir \
    playwright \
    sqlalchemy \
    flask \
    python-dotenv \
    requests \
    InquirerPy

RUN playwright install chromium --with-deps

# ---- Application code ---------------------------------------------------
COPY src/ ./src/

# Persistent data lives in /app/data (bind-mounted in compose)
RUN mkdir -p /app/data/downloads

# ---- Environment --------------------------------------------------------
ENV PYTHONPATH=/app
ENV GLASSROOM_DATA_DIR=/app/data
# Virtual framebuffer display used by Playwright during headed login
ENV DISPLAY=:99

EXPOSE 3000
# noVNC web-based VNC viewer — lets parents log in from their browser
EXPOSE 6080

# ---- Entrypoint ---------------------------------------------------------
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
