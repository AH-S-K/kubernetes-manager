import re

from rest_framework import serializers

NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
CPU_RE = re.compile(r"^(?:[1-9][0-9]*m|[0-9]*\.[1-9][0-9]*|[1-9][0-9]*(?:\.[0-9]+)?)$")
MEMORY_RE = re.compile(r"^(?:[1-9][0-9]*(?:Ki|Mi|Gi|Ti)|[1-9][0-9]*(?:\.[0-9]+)?(?:K|M|G|T)?)$")
ADDRESS_RE = re.compile(r"^[a-zA-Z0-9.-]+:\d+$")

PROTECTED_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease", "default", "django-k8s-manager", "django-manager", "monitoring-system"}

def validate_k8s_name(value):
    value = value.strip()
    if not value:
        raise serializers.ValidationError("Name is required.")

    if value.lower() in PROTECTED_NAMESPACES:
        raise serializers.ValidationError(f"'{value}' is a reserved system namespace and cannot be managed.")

    if len(value) > 63:
        raise serializers.ValidationError("Name must be at most 63 characters.")

    if not NAME_RE.fullmatch(value):
        raise serializers.ValidationError(
            "Name must be lowercase alphanumeric with optional '-' in middle."
        )

    return value


def validate_cpu(value):
    value = value.strip()
    if not CPU_RE.fullmatch(value):
        raise serializers.ValidationError(
            "Invalid CPU quantity. Examples: 100m, 500m, 1, 1.5"
        )
    return value


def validate_memory(value):
    value = value.strip()
    if not MEMORY_RE.fullmatch(value):
        raise serializers.ValidationError(
            "Invalid memory quantity. Examples: 128Mi, 512Mi, 1Gi"
        )
    return value


def validate_address(value):
    value = value.strip()

    if "://" in value:
        value = value.split("://", 1)[1]

    value = value.split("/", 1)[0]

    if not ADDRESS_RE.fullmatch(value):
        raise serializers.ValidationError(
            "Address must be host:port, e.g. 1.2.3.4:6443"
        )

    return value