FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
# The SQLite DDL already ships inside the wheel; db/ is copied so the optional PostgreSQL
# migrations can run from this image as well.
COPY db ./db
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY scripts ./scripts
# The container defaults to the local SQLite tier and writes only inside its own data volume.
# Setting PASSBUDGET_DATABASE_URL switches it to the optional PostgreSQL tier.
ENV PASSBUDGET_DATA_DIR=/app/data
RUN mkdir -p /app/data && chown -R 65532:65532 /app/data
VOLUME ["/app/data"]
USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "semantix_passbudget.interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

