FROM python:3.11-slim

# OS deps (include runtime libs Piper may use)
RUN apt-get update && apt-get install -y \
      curl ca-certificates libsndfile1 libespeak-ng1 libstdc++6 espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Python deps
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ----- Install Piper TTS (NOT the GTK app) -----
# Unpack with --strip-components=1 so the binary ends up at /opt/piper/piper
ENV PIPER_URL=https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz
RUN mkdir -p /opt/piper \
 && curl -fL "$PIPER_URL" -o /tmp/piper.tgz \
 && tar xzf /tmp/piper.tgz -C /opt/piper --strip-components=1 \
 && chmod +x /opt/piper/piper \
 && ln -sf /opt/piper/piper /usr/local/bin/piper \
 && echo "/opt/piper/lib" > /etc/ld.so.conf.d/piper.conf \
 && ldconfig \
 && piper --version

# Piper needs to find espeak data
ENV ESPEAKNG_DATA=/opt/piper/espeak-ng-data

# App
COPY main.py ./main.py
COPY api_keys.txt ./api_keys.txt

EXPOSE 8080
CMD ["uvicorn","main:api","--host","0.0.0.0","--port","8080"]
