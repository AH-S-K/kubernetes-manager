import os

from celery import Celery
from celery.signals import worker_ready

from prometheus_client import start_http_server

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

@worker_ready.connect
def start_metrics_server(**kwargs):
    """
    When the Celery worker becomes ready, it opens a dedicated port
    for exporting background task metrics (backups).
    """
    metrics_port = int(os.environ.get("CELERY_METRICS_PORT", 8001))
    try:
        start_http_server(metrics_port)
        print(f"[METRICS] Celery Prometheus metrics server running on port {metrics_port}")
    except Exception as e:
        print(f"[METRICS] Could not start Celery metrics server: {e}")
