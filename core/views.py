from django.db import connection
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import ValidationError
from .serializers import (
    AppCreateSerializer,
    AppUpdateSerializer,
    ClusterCreateSerializer,
    ClusterReadSerializer,
    NamespaceCreateSerializer,
    NamespaceReadSerializer,
)
from .services import apps as app_service
from .services import clusters as cluster_service
from .services import namespaces as namespace_service
from .tasks import backup

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
    

class BackupView(APIView):
    def post(self, request):
        task = backup.delay()

        return Response(
            {
                "message": "Backup task queued.",
                "task_id": task.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )