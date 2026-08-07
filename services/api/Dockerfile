FROM python:3.12-slim

# libsndfile + ffmpeg are required by librosa/soundfile for decoding uploads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/media

EXPOSE 8000

CMD ["uvicorn", "muse.main:app", "--host", "0.0.0.0", "--port", "8000"]
