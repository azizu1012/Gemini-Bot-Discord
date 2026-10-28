# Azuris Discord bot — single-replica image.
#
# Nguyên tắc:
# - Không bake secret nào vào image (.env bị loại bởi .dockerignore,
#   truyền vào lúc chạy qua `env_file` trong docker-compose.yml).
# - Data không nằm trong image: mọi thư mục ghi (data, uploaded_files,
#   logs, assets/encrypted) đều là bind-mount ra host lúc chạy.
# - Chạy bằng user thường (non-root).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Chỉ cần CA certs cho TLS dial-out (Discord WS, LLM router, search APIs).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# UID 1000 mặc định khớp user host thông thường → bind-mount không dính
# lỗi permission. Host dùng UID khác thì build với --build-arg APP_UID=<uid>.
ARG APP_UID=1000
RUN useradd --uid "$APP_UID" --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src/ ./src/
COPY run_bot.py main.py ./

# Thư mục runtime (lúc chạy sẽ bị bind-mount đè lên — tạo sẵn để
# `docker run` không có volume vẫn không crash, và để rõ ownership).
RUN mkdir -p data uploaded_files logs assets/encrypted \
    && chown -R appuser:appuser /app

USER appuser

# run_bot.py tự chạy preflight (check DB, deps, đường ghi) trước khi start bot.
ENTRYPOINT ["python", "run_bot.py"]
