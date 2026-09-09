FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY dpdp_rag /app/dpdp_rag

ENV PYTHONUNBUFFERED=1
ENV DPDP_COORDINATOR_DB=/data/dpdp-coordinator.sqlite3
VOLUME ["/data"]
EXPOSE 8787

CMD ["uvicorn", "dpdp_rag.coordinator:app", "--host", "0.0.0.0", "--port", "8787"]
