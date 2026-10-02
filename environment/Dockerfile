FROM python:3.13-slim-bookworm
WORKDIR /app
COPY data/ /app/data/
COPY inspect_trace.py /app/inspect_trace.py
COPY tracekit/ /app/tracekit/
RUN chmod +x /app/inspect_trace.py && mkdir -p /app/output
CMD ["sleep", "infinity"]
