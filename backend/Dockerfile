FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --requirement backend/requirements.txt

RUN useradd --create-home framefleet \
    && mkdir --parents /data/uploads \
    && chown framefleet:framefleet /data/uploads

COPY --chown=framefleet:framefleet backend ./backend

USER framefleet

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
