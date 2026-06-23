FROM python:3.11-slim
WORKDIR /app
COPY index.html styles.css mock-data.js app.js server.py ./
EXPOSE 8088
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8088"]
