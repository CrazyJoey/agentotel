FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend_api.py ./
EXPOSE 8091
CMD ["python3", "backend_api.py", "--host", "0.0.0.0", "--port", "8091"]
