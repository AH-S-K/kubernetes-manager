from celery import shared_task


@shared_task
def backup():
    print("backup is ready")