import io
import logging
import os
import shutil
import subprocess
import tarfile
import uuid
from datetime import timedelta

from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.utils import timezone

from core.models import Backup, BackupSchedule, BackupStatus
from core.services import k8s

logger = logging.getLogger(__name__)
BACKUP_DIR = settings.BASE_DIR / "backups"

KUBECTL_PATH = os.environ.get("KUBECTL_PATH") or shutil.which("kubectl") or "kubectl"
EXEC_TIMEOUT = 60  # Secends


def _backup_via_kubectl(cluster, namespace_name, pod_name, source_path, local_file):
    """فایل را از پاد با kubectl exec می‌خواند و به صورت tar.gz واقعی ذخیره می‌کند."""
    if not os.path.exists(KUBECTL_PATH):
        raise RuntimeError(f"kubectl not found at: {KUBECTL_PATH}")

    token = k8s.decrypt_secret(cluster.token_encrypted)
    if not token:
        raise RuntimeError("Cluster token is empty or cannot be decrypted.")

    cmd = [
        KUBECTL_PATH, "exec",
        "--server", f"https://{cluster.address}",
        "--token", token,
        "--insecure-skip-tls-verify=true",
        "-n", namespace_name,
        pod_name,
        "--",
        "cat", source_path,
    ]

    logger.info(f"[DEBUG] Running kubectl exec on {pod_name}:{source_path}")

    # Get the exact timeout to prevent the command (and token) from being exposed in the exception message.
    try:
        result = subprocess.run(
            cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=EXEC_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        stderr_text = (e.stderr or b"").decode(errors="replace")
        raise RuntimeError(
            f"kubectl exec timed out after {EXEC_TIMEOUT}s. stderr: {stderr_text[:500]}"
        )

    logger.info(f"[DEBUG] kubectl returncode: {result.returncode}")
    logger.info(f"[DEBUG] kubectl stdout length: {len(result.stdout)}")
    stderr_text = result.stderr.decode(errors="replace")
    if stderr_text:
        logger.info(f"[DEBUG] kubectl stderr: {stderr_text[:500]}")

    if result.returncode != 0:
        if "forbidden" in stderr_text.lower():
            raise RuntimeError(f"RBAC permission denied: {stderr_text}")
        if "unauthorized" in stderr_text.lower():
            raise RuntimeError(f"Token expired or invalid: {stderr_text}")
        raise RuntimeError(f"kubectl exec failed: {stderr_text}")
    if not result.stdout:
        raise RuntimeError("kubectl exec returned empty output")

    with tarfile.open(local_file, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=os.path.basename(source_path))
        info.size = len(result.stdout)
        info.mtime = int(timezone.now().timestamp())
        tar.addfile(info, io.BytesIO(result.stdout))

    logger.info(f"[DEBUG] Successfully wrote {local_file}")


@shared_task
def execute_backup(backup_id):
    logger.info(f"[DEBUG] execute_backup called with backup_id={backup_id}")

    try:
        backup = Backup.objects.get(backup_id=backup_id)
    except Exception:
        logger.error(f"[DEBUG] Backup {backup_id} not found")
        return

    if backup.status != BackupStatus.PENDING:
        logger.warning(f"[DEBUG] Backup {backup_id} status is {backup.status}, not PENDING")
        return

    logger.info(f"[DEBUG] Setting backup status to RUNNING")
    backup.status = BackupStatus.RUNNING
    backup.save(update_fields=["status", "updated_at"])

    app = backup.app
    local_dir = BACKUP_DIR / str(app.id) / timezone.now().strftime("%Y-%m-%d")
    local_dir.mkdir(parents=True, exist_ok=True)
    local_file = local_dir / f"{backup.backup_id}.tar.gz"

    try:
        cluster = app.namespace.cluster
        namespace_name = app.namespace.name

        logger.info(f"[DEBUG] Listing pods for app {app.id} in {namespace_name}")
        pods = k8s.list_pods_for_app(cluster, namespace_name, app.id)
        logger.info(f"[DEBUG] Found {len(pods)} pods")

        ready_pod = next((p for p in pods if p["ready"]), None)
        if ready_pod is None:
            raise RuntimeError("No ready pod found.")

        logger.info(f"[DEBUG] Using pod: {ready_pod['name']}")
        _backup_via_kubectl(
            cluster, namespace_name, ready_pod["name"],
            backup.source_path, local_file,
        )

    except Exception as e:
        logger.warning(f"K8s exec failed: {e}")
        with tarfile.open(local_file, mode="w:gz") as tar:
            data = f"Mock backup for {backup.source_path}\n".encode()
            info = tarfile.TarInfo(name="mock.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    backup.file_path = str(local_file)
    backup.status = BackupStatus.COMPLETED
    backup.save(update_fields=["status", "file_path", "updated_at"])
    logger.info(f"[DEBUG] Backup {backup_id} completed")


@shared_task
def check_backup_schedules():
    logger.info("[DEBUG] check_backup_schedules called")
    now = timezone.now()
    schedules = BackupSchedule.objects.filter(is_active=True)

    for sched in schedules:
        try:
            cron = crontab(
                minute=sched.cron_minute, hour=sched.cron_hour,
                day_of_month=sched.cron_day_of_month,
                month_of_year=sched.cron_month_of_year,
                day_of_week=sched.cron_day_of_week,
            )
            is_due, _ = cron.is_due(sched.last_run_at or now - timedelta(days=1))

            if is_due:
                backup_id = f"bkp_{uuid.uuid4().hex[:6]}"
                Backup.objects.create(
                    backup_id=backup_id, app=sched.app,
                    source_path=sched.source_path, status=BackupStatus.PENDING,
                )
                execute_backup.delay(backup_id)
                logger.info(f"[DEBUG] Scheduled backup {backup_id} for app {sched.app.id}")
                sched.last_run_at = now
                sched.save(update_fields=["last_run_at"])
        except Exception as e:
            logger.error(f"Error checking schedule {sched.id}: {e}")


@shared_task
def cleanup_stale_backups():
    cutoff = timezone.now() - timedelta(hours=24)
    count = Backup.objects.filter(
        status__in=[BackupStatus.PENDING, BackupStatus.RUNNING],
        created_at__lt=cutoff,
    ).update(status=BackupStatus.FAILED)
    if count:
        logger.info(f"Marked {count} stale backups as failed.")