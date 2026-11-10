FROM python:3.12-slim

WORKDIR /app
COPY src/ /app/src/

ENV DB_PATH=/data/app.db
ENV PORT=8080
EXPOSE 8080

CMD ["python3", "/app/src/server.py"]
