FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data
WORKDIR /app
COPY --from=build /install /usr/local
COPY plex_auto_myshows/ ./plex_auto_myshows/
RUN useradd -u 1000 -m app && mkdir -p /data && chown -R app:app /data /app
USER app
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "plex_auto_myshows"]
