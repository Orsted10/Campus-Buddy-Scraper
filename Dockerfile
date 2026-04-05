FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Start the FastAPI server
CMD ["uvicorn", "culko_api_server:app", "--host", "0.0.0.0", "--port", "10000"]
