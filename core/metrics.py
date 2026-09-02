import time
from contextlib import contextmanager
from prometheus_client import Counter, Histogram, Gauge

# 1. Total number of Kubernetes operations categorized by resource, operation type, and outcome (success/error)
k8s_operations_total = Counter(
    'hamamooz_kubernetes_operations_total',
    'How many Kubernetes operations ended in each outcome?',
    ['resource', 'operation', 'outcome']
)

# 2. Duration of each Kubernetes operation measured in seconds
k8s_operation_duration_seconds = Histogram(
    'hamamooz_kubernetes_operation_duration_seconds',
    'How long did each Kubernetes operation take?',
    ['resource', 'operation']
)

# 3. Total number of backup jobs that have reached a terminal state (completed/failed)
backup_jobs_total = Counter(
    'hamamooz_backup_jobs_total',
    'How many backup jobs reached each terminal outcome?',
    ['outcome']
)

# 4. Duration of the backup process measured in seconds
backup_duration_seconds = Histogram(
    'hamamooz_backup_duration_seconds',
    'How long did backup work take?'
)

# 5. Number of backups that are currently in progress (Running)
backups_in_progress = Gauge(
    'hamamooz_backups_in_progress',
    'How many backups are running now?'
)


@contextmanager
def track_k8s_operation(resource: str, operation: str):
    """
    Context manager for tracking operation duration with nanosecond precision and recording the operation outcome (success/error).
    If the operation completes successfully, outcome='success' is recorded; otherwise, if any error occurs, outcome='error' is recorded.
    """
    start_time = time.perf_counter()
    outcome = 'error'
    try:
        yield
        outcome = 'success'
    finally:
        duration = time.perf_counter() - start_time
        k8s_operations_total.labels(
            resource=resource,
            operation=operation,
            outcome=outcome
        ).inc()
        k8s_operation_duration_seconds.labels(
            resource=resource,
            operation=operation
        ).observe(duration)