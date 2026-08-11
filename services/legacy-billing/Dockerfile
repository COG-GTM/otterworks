FROM python:3.12-slim

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .

EXPOSE 8096
CMD ["gunicorn", "--bind", "0.0.0.0:8096", "app:app"]
