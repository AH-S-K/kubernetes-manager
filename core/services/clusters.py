from django.db import transaction

from core.models import Cluster
from .crypto import encrypt_secret


def create_cluster(validated_data):
    token = validated_data.pop("token")
    ca_cert = validated_data.pop("ca_cert", "")

    with transaction.atomic():
        cluster = Cluster.objects.create(
            token_encrypted=encrypt_secret(token),
            ca_cert=ca_cert,
            **validated_data,
        )

    return cluster


def list_clusters():
    return Cluster.objects.all().order_by("id")