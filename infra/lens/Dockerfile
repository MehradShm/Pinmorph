FROM python:3.12-slim-bookworm
WORKDIR /lens
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir fastapi==0.128.0 uvicorn==0.40.0 python-multipart==0.0.22 pillow==12.1.0 numpy==2.2.6 ftfy==6.3.1 regex==2025.11.3
COPY vendor ./vendor
COPY server.py ./
RUN useradd --uid 10001 --create-home lens
USER lens
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
