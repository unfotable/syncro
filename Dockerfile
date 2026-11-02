FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY syncro ./syncro
COPY tests ./tests

ENV SYNCRO_HOST=0.0.0.0 \
    SYNCRO_PORT=8787 \
    SYNCRO_DATA=/app/syncro_data

VOLUME ["/app/syncro_data"]
EXPOSE 8787

CMD ["python", "app.py"]
