from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from core.exceptions import ConflictError, NotFoundError
from core.models import Cluster, Namespace, NamespaceState

from . import k8s


def create_namespace(cluster_id, name):
    try:
        cluster = Cluster.objects.get(id=cluster_id)
    except Cluster.DoesNotExist:
        raise NotFoundError(
            "Cluster not found.",
            {"cluster_id": cluster_id},
        )

    try:
        with transaction.atomic():
            namespace = Namespace.objects.create(
                cluster=cluster,
                name=name,
                state=NamespaceState.CREATING,
            )
    except IntegrityError:
        raise ConflictError(
            "Namespace already exists for this cluster.",
            {
                "cluster_id": cluster_id,
                "namespace": name,
            },
        )

    try:
        k8s.create_k8s_namespace(
            cluster=cluster,
            name=namespace.name,
            namespace_id=namespace.id,
        )
    except Exception:
        namespace.delete()
        raise

    namespace.state = NamespaceState.ACTIVE
    namespace.save(update_fields=["state", "updated_at"])

    return namespace


def list_namespaces(cluster_id):
    if not Cluster.objects.filter(id=cluster_id).exists():
        raise NotFoundError(
            "Cluster not found.",
            {"cluster_id": cluster_id},
        )

    return Namespace.objects.filter(cluster_id=cluster_id).annotate(app_count=Count('apps')).order_by("id")


def delete_namespace(namespace_id):
    try:
        with transaction.atomic():
            namespace = Namespace.objects.select_for_update().get(id=namespace_id)

            if namespace.state == NamespaceState.DELETING:
                raise ConflictError(
                    "Namespace is already being deleted.",
                    {"namespace_id": namespace_id},
                )

            if namespace.apps.exists():
                raise ConflictError(
                    "Namespace has apps. Delete apps first.",
                    {"namespace_id": namespace_id},
                )

            namespace.state = NamespaceState.DELETING
            namespace.save(update_fields=["state", "updated_at"])
    except Namespace.DoesNotExist:
        raise NotFoundError(
            "Namespace not found.",
            {"namespace_id": namespace_id},
        )

    try:
        k8s.delete_k8s_namespace(
            cluster=namespace.cluster,
            name=namespace.name,
        )
    except Exception:
        Namespace.objects.filter(id=namespace_id).update(
            state=NamespaceState.DELETE_FAILED,
            updated_at=timezone.now(),
        )
        raise