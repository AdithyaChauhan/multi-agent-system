FROM python:3.12-slim

WORKDIR /app

RUN pip install fastapi uvicorn

COPY mock_services/ ./mock_services/

EXPOSE 9000

CMD ["uvicorn", "mock_services.carrier_api:app", "--host", "0.0.0.0", "--port", "9000"]
