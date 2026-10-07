# ErgoVision — container image for Render / Railway / Fly / any Docker host.
#
#   docker build -t ergovision .
#   docker run -p 8000:8000 ergovision     then open http://localhost:8000/
#
# The 9 MB pose model is not in git; it is fetched during the build so the
# running container never has to reach the network on a cold start.

FROM python:3.12-slim

# OpenCV and MediaPipe need these shared libraries even for headless work.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ERGOVISION_DB=/data/ergovision.db

WORKDIR /app

# Dependencies first, so a code change does not re-install MediaPipe.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pull the pose landmarker into the image (download_model.py --yes skips the prompt).
RUN python download_model.py --yes --variant full \
    && python buildcheck.py

# The register lives on a volume when one is mounted; without it the data is
# ephemeral and resets on every deploy (fine for a demo, see README).
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
ENV PORT=8000

# One worker keeps the MediaPipe graph (and its memory) single-instance; the
# threads handle concurrent requests while one inference holds the engine lock.
CMD exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 180 app:app
