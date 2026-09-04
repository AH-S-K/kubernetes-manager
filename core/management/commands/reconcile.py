from genericpath import exists
import time

from celery import app
from django.core.management.base import BaseCommand

from core.exceptions import DomainError
from core.models import App, AppState, Namespace, NamespaceState
from core.services import k8s

from datetime import timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = "Reconcile DB state with Kubernetes state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run reconciler continuously.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Interval in seconds for loop mode.",
        )

    def handle(self, *args, **options):
        if options["loop"]:
            interval = options["interval"]
            self.stdout.write(f"Starting reconciler loop every {interval}s")

            while True:
                self.reconcile()
                time.sleep(interval)
        else:
            self.reconcile()

    def reconcile(self):
        self.reconcile_namespaces()
        self.reconcile_apps()
        self.stdout.write(self.style.SUCCESS("Reconcile cycle completed."))

    def reconcile_namespaces(self):
        namespaces = Namespace.objects.select_related("cluster").all()

        for namespace in namespaces:
            try:
                exists = k8s.namespace_exists(namespace.cluster, namespace.name)
            except DomainError as e:
                self.stderr.write(
                    f"Namespace {namespace.id} check failed: {str(e)}"
                )
                continue

            try:
                if namespace.state == NamespaceState.CREATING:
                    if exists:
                        namespace.state = NamespaceState.ACTIVE
                        namespace.save(update_fields=["state", "updated_at"])
                    elif (timezone.now() - namespace.created_at) > timedelta(minutes=3):
                        namespace.delete()

                elif namespace.state == NamespaceState.CREATE_FAILED:
                    if exists:
                        namespace.state = NamespaceState.ACTIVE
                        namespace.save(update_fields=["state", "updated_at"])

                elif namespace.state in [
                    NamespaceState.DELETING,
                    NamespaceState.DELETE_FAILED,
                ]:
                    if not exists:
                        namespace.delete()
                    else:
                        k8s.delete_k8s_namespace(namespace.cluster, namespace.name)

                elif namespace.state == NamespaceState.ACTIVE:
                    if not exists:
                        namespace.state = NamespaceState.MISSING
                        namespace.save(update_fields=["state", "updated_at"])

                elif namespace.state in [
                    NamespaceState.MISSING,
                    NamespaceState.ERROR,
                ]:
                    if exists:
                        namespace.state = NamespaceState.ACTIVE
                        namespace.save(update_fields=["state", "updated_at"])

            except DomainError as e:
                self.stderr.write(
                    f"Namespace {namespace.id} reconcile failed: {str(e)}"
                )

    def reconcile_apps(self):
        apps = App.objects.select_related("namespace__cluster").all()

        for app in apps:
            try:
                deployment = k8s.get_k8s_deployment(
                    app.namespace.cluster,
                    app.namespace.name,
                    app.name,
                )
                exists = deployment is not None
            except DomainError as e:
                self.stderr.write(f"App {app.id} check failed: {str(e)}")
                continue

            try:
                if app.state == AppState.CREATING:
                    if exists:
                        app.state = AppState.ACTIVE
                        app.save(update_fields=["state", "updated_at"])
                    elif (timezone.now() - app.created_at) > timedelta(minutes=3):
                        app.delete()

                elif app.state == AppState.CREATE_FAILED:
                    if exists:
                        app.state = AppState.ACTIVE
                        app.save(update_fields=["state", "updated_at"])
                        
                elif app.state in [
                    AppState.UPDATING,
                    AppState.UPDATE_FAILED,
                ]:
                    if exists:
                        k8s.patch_k8s_deployment(
                            app.namespace.cluster,
                            app.namespace.name,
                            app,
                        )
                        app.state = AppState.ACTIVE
                        app.save(update_fields=["state", "updated_at"])
                    else:
                        app.state = AppState.MISSING
                        app.save(update_fields=["state", "updated_at"])

                elif app.state in [
                    AppState.DELETING,
                    AppState.DELETE_FAILED,
                ]:
                    if not exists:
                        app.delete()
                    else:
                        k8s.delete_k8s_deployment(
                            app.namespace.cluster,
                            app.namespace.name,
                            app.name,
                        )

                elif app.state == AppState.ACTIVE:
                    if not exists:
                        app.state = AppState.MISSING
                        app.save(update_fields=["state", "updated_at"])

                elif app.state in [
                    AppState.MISSING,
                    AppState.ERROR,
                ]:
                    if exists:
                        app.state = AppState.ACTIVE
                        app.save(update_fields=["state", "updated_at"])

            except DomainError as e:
                self.stderr.write(f"App {app.id} reconcile failed: {str(e)}")