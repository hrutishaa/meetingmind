FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MEETINGMIND_DB=/data/meetingmind.db
COPY pyproject.toml README.md LICENSE ./
COPY meetingmind ./meetingmind
RUN pip install --no-cache-dir ".[api]" && useradd --create-home app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "meetingmind.api:app", "--host", "0.0.0.0", "--port", "8000"]
