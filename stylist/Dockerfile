ARG BASE=python:3.12-slim
FROM ${BASE}
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 GOOGLE_GENAI_USE_ENTERPRISE=0
COPY requirements.txt /app/stylist/requirements.txt
RUN pip install -r /app/stylist/requirements.txt
COPY . /app/stylist
WORKDIR /app
CMD ["sh", "-c", "exec uvicorn stylist.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
