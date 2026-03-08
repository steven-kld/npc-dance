FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:2
ENV NO_VNCVIEWER=1

# System dependencies
RUN apt-get update && apt-get install -y \
    xvfb \
    x11vnc \
    xclip \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    python3 \
    python3-pip \
    wget \
    ca-certificates \
    novnc \
    websockify \
    python3-tk \
    # GPU / GL libraries (for Chrome hardware acceleration)
    libgl1-mesa-dri \
    libglx-mesa0 \
    libgles2 \
    mesa-utils \
    && rm -rf /var/lib/apt/lists/*

# Google Chrome
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — Chrome sandbox works without --no-sandbox
RUN useradd -m -s /bin/bash npc

WORKDIR /home/npc/app

COPY --chown=npc:npc requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY --chown=npc:npc . .

RUN chmod +x docker-start.sh

# noVNC: redirect / → vnc.html so the web root doesn't expose a directory listing
RUN echo '<meta http-equiv="refresh" content="0; url=vnc.html">' > /usr/share/novnc/index.html

# Pre-create X11 socket dir so Xvfb can run as non-root
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

USER npc

# noVNC browser UI + agent API
EXPOSE 6080
EXPOSE 8000

CMD ["bash", "docker-start.sh"]
