# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.0.1

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" "poetry-plugin-export>=1.8"

# Isolated venv for app deps. Without this, `pip install --user` would see
# transitive deps already installed in /usr/local site-packages by Poetry
# itself (cffi, charset-normalizer, etc.) and silently no-op them with
# "Requirement already satisfied" — they never get copied to runtime.
# That regression (#167) caused scrape_deaths to fail every fire on prod
# with ModuleNotFoundError: No module named '_cffi_backend'.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml poetry.lock ./
RUN poetry export --without-hashes --only=main -o requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Build-time guardrail. Asserts the SSL-stack deps that scrapy/twisted need
# at import time are actually importable. Fails the docker build if any
# regresses — better than discovering it the next time someone tries to
# scrape on prod and the silent failure mode amplifies for days.
RUN /opt/venv/bin/python -c "import _cffi_backend, cryptography, OpenSSL._util, charset_normalizer; print('SSL-stack import OK')"


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash --uid 1000 app
USER app
WORKDIR /app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app . /app

# Collect static assets into STATIC_ROOT (/app/staticfiles) so whitenoise can
# serve them at runtime. Build-time env vars are placeholders — collectstatic
# only needs the settings module to import successfully, not real infra
# credentials. None of these values are baked into the image (RUN-scoped).
RUN DJANGO_SECRET_KEY=build-time-only-not-used \
    DATABASE_URL=sqlite:///build.sqlite3 \
    REDIS_URL=redis://localhost:6379/0 \
    CELERY_BROKER_URL=redis://localhost:6379/1 \
    CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
    python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8000/health/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
