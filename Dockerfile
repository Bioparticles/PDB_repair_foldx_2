FROM python:3.11.9-slim-bookworm AS builder

RUN pip install poetry

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && poetry install --no-root

# Get service files
ADD tool-service.py foldx_20251231 ./
RUN chmod +x foldx_20251231

# VERSION INFORMATION
ARG VERSION ???
ENV VERSION=$VERSION
ENV PORT=80

# Command to run
ENTRYPOINT ["python",  "/app/tool-service.py"]