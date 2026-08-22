import uuid
import redis

from django.db import connection
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ValidationError
from core.serializers import (
    AppCreateSerializer,
    AppUpdateSerializer,
    ClusterCreateSerializer,
    ClusterReadSerializer,
    NamespaceCreateSerializer,
    NamespaceReadSerializer,
)
from core.services import apps as app_service
from core.services import clusters as cluster_service
from core.services import namespaces as namespace_service
from core.tasks import execute_backup


class ClusterListCreateView(APIView):
    def get(self, request):
        clusters = cluster_service.list_clusters()
        serializer = ClusterReadSerializer(clusters, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ClusterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cluster = cluster_service.create_cluster(serializer.validated_data)

        return Response(
            ClusterReadSerializer(cluster).data,
            status=status.HTTP_201_CREATED,
        )


class NamespaceListCreateView(APIView):
    def get(self, request):
        cluster_id = request.query_params.get("cluster_id")

        if cluster_id is None:
            raise ValidationError("cluster_id query parameter is required.")

        try:
            cluster_id = int(cluster_id)
        except (TypeError, ValueError):
            raise ValidationError("cluster_id must be an integer.")

        namespaces = namespace_service.list_namespaces(cluster_id)
        serializer = NamespaceReadSerializer(namespaces, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = NamespaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        namespace = namespace_service.create_namespace(
            cluster_id=serializer.validated_data["cluster_id"],
            name=serializer.validated_data["name"],
        )

        return Response(
            NamespaceReadSerializer(namespace).data,
            status=status.HTTP_201_CREATED,
        )


class NamespaceDeleteView(APIView):
    def delete(self, request, pk):
        namespace_service.delete_namespace(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppListCreateView(APIView):
    def get(self, request):
        namespace_id = request.query_params.get("namespace_id")

        if namespace_id is None:
            raise ValidationError("namespace_id query parameter is required.")

        try:
            namespace_id = int(namespace_id)
        except (TypeError, ValueError):
            raise ValidationError("namespace_id must be an integer.")

        result = app_service.list_apps(namespace_id)
        return Response(result, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = AppCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        app = app_service.create_app(serializer.validated_data)

        return Response(
            app_service.app_basic_dict(app),
            status=status.HTTP_201_CREATED,
        )


class AppDetailView(APIView):
    def get(self, request, pk):
        result = app_service.get_app_detail(pk)
        return Response(result, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        serializer = AppUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not serializer.validated_data:
            raise ValidationError("No fields to update.")

        app = app_service.update_app(pk, serializer.validated_data)

        return Response(
            app_service.app_basic_dict(app),
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        return self.patch(request, pk)

    def delete(self, request, pk):
        app_service.delete_app(pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LiveHealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class ReadyHealthView(APIView):
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception as e:
            return Response(
                {"status": "error", "detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"status": "ready"})
    

redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)

class BackupView(APIView):
    def post(self, request):
        app_id = request.data.get("app_id")
        source_path = request.data.get("source_path")
        schedule = request.data.get("schedule")

        if not app_id or not source_path:
            raise ValidationError("app_id and source_path are required.")

        try:
            app = App.objects.get(id=app_id)
        except App.DoesNotExist:
            raise NotFoundError("App not found.", {"app_id": app_id})

        backup_id = f"bkp_{uuid.uuid4().hex[:6]}"
        Backup.objects.create(
            backup_id=backup_id, app=app,
            source_path=source_path, status="pending"
        )
        execute_backup.delay(backup_id)

        if schedule:
            parts = schedule.split()
            if len(parts) != 5:
                raise ValidationError("Invalid cron expression. Expected 5 fields.")
            BackupSchedule.objects.create(
                app=app, source_path=source_path,
                cron_minute=parts[0], cron_hour=parts[1],
                cron_day_of_month=parts[2], cron_month_of_year=parts[3],
                cron_day_of_week=parts[4]
            )

        return Response({"backup_id": backup_id, "status": "pending"}, status=status.HTTP_202_ACCEPTED)

    def get(self, request):
        app_id = request.query_params.get("app_id")
        if not app_id:
            raise ValidationError("app_id query parameter is required.")
        backups = Backup.objects.filter(app_id=app_id).order_by("-created_at")
        return Response([{"backup_id": b.backup_id, "status": b.status} for b in backups])

class BackupDetailView(APIView):
    def get(self, request, backup_id):
        try:
            backup = Backup.objects.get(backup_id=backup_id)
        except Backup.DoesNotExist:
            raise NotFoundError("Backup not found.", {"backup_id": backup_id})
        return Response({
            "backup_id": backup.backup_id,
            "app_id": backup.app_id,
            "status": backup.status
        })