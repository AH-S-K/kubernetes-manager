import redis

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.conf import settings

from core.exceptions import ConflictError, NotFoundError
from core.models import App, AppState, Namespace, NamespaceState

from . import k8s


def _get_app(app_id):
    try:
        return App.objects.select_related("namespace__cluster").get(id=app_id)
    except App.DoesNotExist:
        raise NotFoundError(
            "App not found.",
            {"app_id": app_id},
        )


def app_basic_dict(app):
    return {
        "id": app.id,
        "name": app.name,
        "namespace_id": app.namespace_id,
        "namespace": app.namespace.name,
        "image": app.image,
        "replicas": app.replicas,
        "cpu": app.cpu,
        "memory": app.memory,
        "state": app.state,
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }


def app_detail_dict(app, live):
    base = app_basic_dict(app)
    base.update(
        {
            "ready": live["ready"],
            "deployment_found": live["deployment_found"],
            "desired_replicas": live["desired_replicas"],
            "available_replicas": live["available_replicas"],
            "pods": live["pods"],
        }
    )
    return base


def create_app(validated_data):
    namespace_id = validated_data.pop("namespace_id")

    try:
        namespace = Namespace.objects.select_related("cluster").get(id=namespace_id)
    except Namespace.DoesNotExist:
        raise NotFoundError(
            "Namespace not found.",
            {"namespace_id": namespace_id},
        )

    if namespace.state != NamespaceState.ACTIVE:
        raise ConflictError(
            "Namespace is not active.",
            {
                "namespace_id": namespace_id,
                "state": namespace.state,
            },
        )

    try:
        with transaction.atomic():
            app = App.objects.create(
                namespace=namespace,
                state=AppState.CREATING,
                **validated_data,
            )
    except IntegrityError:
        raise ConflictError(
            "App already exists in this namespace.",
            {
                "namespace_id": namespace_id,
                "name": validated_data.get("name"),
            },
        )

    try:
        k8s.create_k8s_deployment(
            cluster=namespace.cluster,
            namespace_name=namespace.name,
            app=app,
        )
    except Exception:
        App.objects.filter(
            id=app.id,
            state=AppState.CREATING,
        ).update(state=AppState.CREATE_FAILED)
        raise

    app.state = AppState.ACTIVE
    app.save(update_fields=["state", "updated_at"])

    return app


def list_apps(namespace_id):
    try:
        namespace = Namespace.objects.select_related("cluster").get(id=namespace_id)
    except Namespace.DoesNotExist:
        raise NotFoundError(
            "Namespace not found.",
            {"namespace_id": namespace_id},
        )

    apps = App.objects.filter(namespace=namespace).order_by("id")
    result = []

    for app in apps:
        live = k8s.get_app_live_status(app)
        result.append(app_detail_dict(app, live))

    return result


def get_app_detail(app_id):
    app = _get_app(app_id)
    live = k8s.get_app_live_status(app)
    return app_detail_dict(app, live)


redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)


def update_app(app_id, data):
    try:
        with transaction.atomic():
            app = (
                App.objects.select_for_update()
                .select_related("namespace__cluster")
                .get(id=app_id)
            )

            if app.state in [AppState.CREATING, AppState.DELETING, AppState.UPDATING]:
                raise ConflictError(
                    "App cannot be updated in current state.",
                    {
                        "app_id": app_id,
                        "state": app.state,
                    },
                )
                
            for field in ["image", "replicas", "cpu", "memory"]:
                if field in data:
                    setattr(app, field, data[field])

            app.state = AppState.UPDATING
            app.save(
                update_fields=[
                    "image",
                    "replicas",
                    "cpu",
                    "memory",
                    "state",
                    "updated_at",
                ]
            )
    except App.DoesNotExist:
        raise NotFoundError(
            "App not found.",
            {"app_id": app_id},
        )

    try:
        k8s.patch_k8s_deployment(
            cluster=app.namespace.cluster,
            namespace_name=app.namespace.name,
            app=app,
        )
    except Exception:
        App.objects.filter(id=app_id).update(
            state=AppState.UPDATE_FAILED,
            updated_at=timezone.now(),
        )
        raise

    with transaction.atomic():
        app = App.objects.select_for_update().get(id=app_id)
        app.state = AppState.ACTIVE
        app.save(update_fields=["state", "updated_at"])

    try:
        redis_client.delete(f"app_live_status:{app_id}")
    except Exception:
        pass

    return app

def delete_app(app_id):
    try:
        with transaction.atomic():
            app = App.objects.select_for_update().get(id=app_id)

            if app.state in [AppState.DELETING, AppState.CREATING, AppState.UPDATING]:
                raise ConflictError(
                    "App cannot be deleted in current state.",
                    {
                        "app_id": app_id,
                        "state": app.state,
                    },
                )

            app.state = AppState.DELETING
            app.save(update_fields=["state", "updated_at"])
    except App.DoesNotExist:
        raise NotFoundError(
            "App not found.",
            {"app_id": app_id},
        )

    try:
        k8s.delete_k8s_deployment(
            cluster=app.namespace.cluster,
            namespace_name=app.namespace.name,
            app_name=app.name,
        )
    except Exception:
        App.objects.filter(id=app_id).update(
            state=AppState.DELETE_FAILED,
            updated_at=timezone.now(),
        )
        raise

    with transaction.atomic():
        App.objects.filter(
            id=app_id,
            state=AppState.DELETING,
        ).delete()

    try:
        redis_client.delete(f"app_live_status:{app_id}")
    except Exception:
        pass