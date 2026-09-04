import logging
import urllib3
import json
import redis
from django.conf import settings
from kubernetes import client
from kubernetes.client.rest import ApiException

from core.exceptions import (
    DomainError,
    K8sConflictError,
    K8sForbiddenError,
    K8sUnavailableError,
    NotFoundError,
    ValidationError,
)
from .crypto import decrypt_secret

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MANAGED_BY_LABEL = "platform.local/managed-by"
MANAGED_BY_VALUE = "django-k8s-task"

NAMESPACE_ID_LABEL = "platform.local/namespace-id"
APP_ID_LABEL = "platform.local/app-id"

APP_NAME_LABEL = "app.kubernetes.io/name"
APP_INSTANCE_LABEL = "app.kubernetes.io/instance"

redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)


def get_clients(cluster):
    token = decrypt_secret(cluster.token_encrypted)

    if not token:
        raise DomainError(
            "Cluster token is empty or cannot be decrypted.",
            {"cluster_id": cluster.id},
        )

    cfg = client.Configuration()

    address = cluster.address.strip()
    if "://" not in address:
        cfg.host = f"https://{address}"
    else:
        cfg.host = address

    cfg.api_key = {
        "authorization": f"Bearer {token}"
    }

    # برای اجرای تمرین روی k3s لوکال/remote ساده‌تر است که TLS verify نشود.
    cfg.verify_ssl = False
    cfg.assert_hostname = False

    api_client = client.ApiClient(cfg)

    core_v1 = client.CoreV1Api(api_client)
    apps_v1 = client.AppsV1Api(api_client)

    return core_v1, apps_v1


def _raise_api_exception(e, details=None):
    details = details or {}

    if isinstance(e, ApiException):
        details.update(
            {
                "status": e.status,
                "reason": e.reason,
            }
        )

        if e.status == 400:
            raise ValidationError("Kubernetes rejected the request.", details)

        if e.status == 403:
            raise K8sForbiddenError("Kubernetes denied access.", details)

        if e.status == 404:
            raise NotFoundError("Kubernetes resource not found.", details)

        if e.status == 409:
            raise K8sConflictError("Resource already exists in Kubernetes.", details)

        raise K8sUnavailableError("Cannot communicate with Kubernetes.", details)

    details.update({"error": str(e)})
    raise K8sUnavailableError("Cannot communicate with Kubernetes.", details)


def _bind_exec_role_to_namespace(cluster, namespace_name):
    core_v1, _ = get_clients(cluster)
    rbac_v1 = client.RbacAuthorizationV1Api(core_v1.api_client)

    role_binding = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": "django-sa-exec-binding",
            "namespace": namespace_name,
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": "django-sa",
                "namespace": "django-manager",
            }
        ],
        "roleRef": {
            "kind": "ClusterRole",
            "name": "django-app-exec-role",
            "apiGroup": "rbac.authorization.k8s.io",
        },
    }

    try:
        rbac_v1.create_namespaced_role_binding(
            namespace=namespace_name,
            body=role_binding,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except ApiException as e:
        if e.status != 409:
            _raise_api_exception(e, {"namespace": namespace_name})
    except Exception as e:
        _raise_api_exception(e, {"namespace": namespace_name})


def create_k8s_namespace(cluster, name, namespace_id):
    core_v1, _ = get_clients(cluster)

    body = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": name,
            "labels": {
                MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                NAMESPACE_ID_LABEL: str(namespace_id),
            },
        },
    }

    details = {
        "cluster_id": cluster.id,
        "namespace": name,
    }

    try:
        core_v1.create_namespace(
            body=body,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
        _bind_exec_role_to_namespace(cluster, name)
    except ApiException as e:
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def delete_k8s_namespace(cluster, name):
    core_v1, _ = get_clients(cluster)

    details = {
        "cluster_id": cluster.id,
        "namespace": name,
    }

    try:
        rbac_v1 = client.RbacAuthorizationV1Api(core_v1.api_client)
        rbac_v1.delete_namespaced_role_binding(
            name="django-sa-exec-binding",
            namespace=name,
            body=client.V1DeleteOptions(),
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete RoleBinding for namespace {name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to delete RoleBinding for namespace {name}: {e}")

    try:
        core_v1.delete_namespace(
            name=name,
            body=client.V1DeleteOptions(),
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def namespace_exists(cluster, name):
    core_v1, _ = get_clients(cluster)

    details = {
        "cluster_id": cluster.id,
        "namespace": name,
    }

    try:
        core_v1.read_namespace(
            name=name,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def _app_labels(app):
    return {
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        APP_NAME_LABEL: app.name,
        APP_INSTANCE_LABEL: str(app.id),
        APP_ID_LABEL: str(app.id),
        NAMESPACE_ID_LABEL: str(app.namespace_id),
    }


def build_deployment_manifest(app):
    labels = _app_labels(app)

    selector = {
        APP_NAME_LABEL: app.name,
        APP_INSTANCE_LABEL: str(app.id),
    }

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": app.name,
            "namespace": app.namespace.name,
            "labels": labels,
        },
        "spec": {
            "replicas": app.replicas,
            "selector": {
                "matchLabels": selector,
            },
            "template": {
                "metadata": {
                    "labels": labels,
                },
                "spec": {
                    "containers": [
                        {
                            "name": app.name,
                            "image": app.image,
                            "resources": {
                                "requests": {
                                    "cpu": app.cpu,
                                    "memory": app.memory,
                                },
                                "limits": {
                                    "cpu": app.cpu,
                                    "memory": app.memory,
                                },
                            },
                        }
                    ]
                },
            },
        },
    }


def create_k8s_deployment(cluster, namespace_name, app):
    _, apps_v1 = get_clients(cluster)

    body = build_deployment_manifest(app)

    details = {
        "cluster_id": cluster.id,
        "namespace": namespace_name,
        "app": app.name,
    }

    try:
        apps_v1.create_namespaced_deployment(
            namespace=namespace_name,
            body=body,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except ApiException as e:
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def delete_k8s_deployment(cluster, namespace_name, app_name):
    _, apps_v1 = get_clients(cluster)

    details = {
        "cluster_id": cluster.id,
        "namespace": namespace_name,
        "app": app_name,
    }

    try:
        apps_v1.delete_namespaced_deployment(
            name=app_name,
            namespace=namespace_name,
            body=client.V1DeleteOptions(),
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def get_k8s_deployment(cluster, namespace_name, app_name):
    _, apps_v1 = get_clients(cluster)

    details = {
        "cluster_id": cluster.id,
        "namespace": namespace_name,
        "app": app_name,
    }

    try:
        return apps_v1.read_namespaced_deployment(
            name=app_name,
            namespace=namespace_name,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except ApiException as e:
        if e.status == 404:
            return None
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def patch_k8s_deployment(cluster, namespace_name, app):
    _, apps_v1 = get_clients(cluster)

    body = {
        "spec": {
            "replicas": app.replicas,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": app.name,
                            "image": app.image,
                            "resources": {
                                "requests": {
                                    "cpu": app.cpu,
                                    "memory": app.memory,
                                },
                                "limits": {
                                    "cpu": app.cpu,
                                    "memory": app.memory,
                                },
                            },
                        }
                    ]
                }
            },
        }
    }

    details = {
        "cluster_id": cluster.id,
        "namespace": namespace_name,
        "app": app.name,
    }

    try:
        apps_v1.patch_namespaced_deployment(
            name=app.name,
            namespace=namespace_name,
            body=body,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except ApiException as e:
        _raise_api_exception(e, details)
    except Exception as e:
        _raise_api_exception(e, details)


def _pod_is_ready(pod):
    if not pod.status:
        return False

    if not pod.status.conditions:
        return False

    for condition in pod.status.conditions:
        if condition.type == "Ready":
            return condition.status == "True"

    return False


def list_pods_for_app(cluster, namespace_name: str, app_id: str) -> list[dict]:
    core_v1, _ = get_clients(cluster)
    label_selector = f"{APP_INSTANCE_LABEL}={app_id}"

    details = {
        "cluster_id": cluster.id,
        "namespace": namespace_name,
        "app_id": app_id,
    }

    try:
        pod_list = core_v1.list_namespaced_pod(
            namespace=namespace_name,
            label_selector=label_selector,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT,
        )
    except (ApiException, Exception) as e:
        _raise_api_exception(e, details)

    result = []
    for pod in pod_list.items:
        metadata = pod.metadata
        status = pod.status
        spec = pod.spec

        # Determine pod phase and readiness
        if metadata and metadata.deletion_timestamp:
            phase = "Terminating"
            ready = False
        else:
            phase = status.phase if status else "Unknown"
            ready = _pod_is_ready(pod)

        # Calculate total container restarts
        container_statuses = status.container_statuses if status else None
        restarts = (
            sum(cs.restart_count for cs in container_statuses)
            if container_statuses
            else 0
        )

        # Format creation timestamp safely
        created_at = (
            metadata.creation_timestamp.isoformat()
            if metadata and metadata.creation_timestamp
            else None
        )

        result.append(
            {
                "name": metadata.name if metadata else "unknown",
                "phase": phase,
                "ready": ready,
                "restarts": restarts,
                "pod_ip": status.pod_ip if status else None,
                "node_name": spec.node_name if spec else None,
                "created_at": created_at,
            }
        )

    return result


def get_app_live_status(app):
    cache_key = f"app_live_status:{app.id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    cluster = app.namespace.cluster
    namespace_name = app.namespace.name
    deployment = get_k8s_deployment(cluster, namespace_name, app.name)

    if deployment is None:
        result = {
            "deployment_found": False, "ready": False,
            "desired_replicas": app.replicas, "available_replicas": 0, "pods": [],
        }
    else:
        pods = list_pods_for_app(cluster, namespace_name, app.id)
        desired = app.replicas
        if deployment.spec and deployment.spec.replicas is not None:
            desired = deployment.spec.replicas

        available = 0
        if deployment.status and deployment.status.available_replicas is not None:
            available = deployment.status.available_replicas

        if desired == 0:
            ready = len(pods) == 0
        else:
            all_pods_ready = bool(pods) and all(pod["ready"] for pod in pods)
            ready = available == desired and len(pods) == desired and all_pods_ready

        result = {
            "deployment_found": True, "ready": ready,
            "desired_replicas": desired, "available_replicas": available, "pods": pods,
        }

    try:
        redis_client.setex(cache_key, 5, json.dumps(result))
    except Exception:
        pass

    return result