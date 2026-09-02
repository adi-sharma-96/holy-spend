FROM node:22-slim AS widget-builder

WORKDIR /build/widget
COPY widget/package.json widget/package-lock.json ./
RUN npm ci
COPY widget/index.html widget/tsconfig.json widget/vite.config.ts ./
COPY widget/src ./src
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY --from=widget-builder /build/widget/dist ./widget/dist

RUN pip install --no-cache-dir .

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
