from rest_framework import serializers

from .models import Cluster, Namespace
from .validators import (
    validate_address,
    validate_cpu,
    validate_k8s_name,
    validate_memory,
)


class ClusterCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    address = serializers.CharField(max_length=255)
    token = serializers.CharField(write_only=True, allow_blank=False)
    ca_cert = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_address(self, value):
        return validate_address(value)


class ClusterReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cluster
        fields = [
            "id",
            "name",
            "address",
            "created_at",
        ]


class NamespaceCreateSerializer(serializers.Serializer):
    cluster_id = serializers.IntegerField()
    name = serializers.CharField(max_length=63)

    def validate_name(self, value):
        return validate_k8s_name(value)


class NamespaceReadSerializer(serializers.ModelSerializer):
    cluster_id = serializers.IntegerField(source="cluster.id", read_only=True)

    class Meta:
        model = Namespace
        fields = [
            "id",
            "cluster_id",
            "name",
            "state",
            "created_at",
            "updated_at",
        ]


class AppCreateSerializer(serializers.Serializer):
    namespace_id = serializers.IntegerField()
    name = serializers.CharField(max_length=63)
    image = serializers.CharField(max_length=255)
    replicas = serializers.IntegerField(min_value=0, default=1)
    cpu = serializers.CharField(default="100m")
    memory = serializers.CharField(default="128Mi")

    def validate_name(self, value):
        return validate_k8s_name(value)

    def validate_cpu(self, value):
        return validate_cpu(value)

    def validate_memory(self, value):
        return validate_memory(value)


class AppUpdateSerializer(serializers.Serializer):
    image = serializers.CharField(required=False, max_length=255)
    replicas = serializers.IntegerField(required=False, min_value=0)
    cpu = serializers.CharField(required=False)
    memory = serializers.CharField(required=False)

    def validate_cpu(self, value):
        return validate_cpu(value)

    def validate_memory(self, value):
        return validate_memory(value)