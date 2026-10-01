FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir poetry==1.8.2
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && poetry install --no-root --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY . .

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd -r -u 1001 appuser

# The export archive the service reads rendered exports back out of. It has to
# exist in the image: a missing directory turns every export read into a 404,
# including the runtime probe's control read.
ENV EXPORT_ARCHIVE_DIR=/var/lib/otterworks/exports
# Demo failure point: "New document" publishes document_created to a
# nonexistent SNS topic (the real topic with a "-v2" suffix), so every click
# fails with a real AWS SNS error, shows a red banner, and calls the Devin
# Automation webhook (DEVIN_AUTOMATION_WEBHOOK_URL) that starts an
# investigation session. docker-compose.yml passes false, so local stacks
# behave like the golden app.
ENV DOC_SVC_CREATE_ALWAYS_FAIL=true
RUN mkdir -p "$EXPORT_ARCHIVE_DIR" \
    && printf 'export archive reachable\n' > "$EXPORT_ARCHIVE_DIR/dast-control.txt" \
    && chown -R appuser "$EXPORT_ARCHIVE_DIR"

USER appuser

EXPOSE 8083
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8083/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083"]
