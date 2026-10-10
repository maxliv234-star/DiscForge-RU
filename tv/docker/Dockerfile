FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY tv_server /app/tv_server
RUN useradd --system --uid 10001 --no-create-home --home-dir /tmp discforge
USER 10001
EXPOSE 8098/tcp 8099/udp
ENTRYPOINT ["python", "-m", "tv_server"]
CMD ["--media-root", "/media", "--host", "0.0.0.0", "--port", "8098", "--token-file", "/config/token", "--no-print-token"]
