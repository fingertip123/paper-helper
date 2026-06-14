FROM python:3.12-slim

WORKDIR /srv/yanzhan

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY tools/ tools/
COPY templates/ templates/
COPY wsgi.py .

ENV YANZHAN_DATA_DIR=/srv/yanzhan/data \
    YANZHAN_MULTIUSER=1 \
    PORT=8765

# 生产环境把 /srv/yanzhan/data 挂载到持久卷，否则重启丢数据
VOLUME ["/srv/yanzhan/data"]

EXPOSE 8765
CMD ["python", "tools/server.py"]
