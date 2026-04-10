FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY main.py ./
COPY README.md ./
COPY world_athletics_scoring_tables_2025.pdf ./
COPY world_athletics_scoring_2025.json ./

EXPOSE 8080

CMD ["python3", "main.py"]
