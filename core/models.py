from django.db import models


class Cluster(models.Model):
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255)
    token_encrypted = models.BinaryField()
    ca_cert = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.id} - {self.name}"


class NamespaceState(models.TextChoices):
    CREATING = "CREATING", "Creating"
    ACTIVE = "ACTIVE", "Active"
    DELETING = "DELETING", "Deleting"
    CREATE_FAILED = "CREATE_FAILED", "Create Failed"
    DELETE_FAILED = "DELETE_FAILED", "Delete Failed"
    MISSING = "MISSING", "Missing"
    ERROR = "ERROR", "Error"


class Namespace(models.Model):
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.CASCADE,
        related_name="namespaces",
    )
    name = models.CharField(max_length=63)
    state = models.CharField(
        max_length=20,
        choices=NamespaceState.choices,
        default=NamespaceState.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "name"],
                name="unique_namespace_per_cluster",
            )
        ]

    def __str__(self):
        return f"{self.id} - {self.name}"


class AppState(models.TextChoices):
    CREATING = "CREATING", "Creating"
    ACTIVE = "ACTIVE", "Active"
    UPDATING = "UPDATING", "Updating"
    DELETING = "DELETING", "Deleting"
    CREATE_FAILED = "CREATE_FAILED", "Create Failed"
    UPDATE_FAILED = "UPDATE_FAILED", "Update Failed"
    DELETE_FAILED = "DELETE_FAILED", "Delete Failed"
    MISSING = "MISSING", "Missing"
    ERROR = "ERROR", "Error"


class App(models.Model):
    namespace = models.ForeignKey(
        Namespace,
        on_delete=models.CASCADE,
        related_name="apps",
    )
    name = models.CharField(max_length=63)
    image = models.CharField(max_length=255)
    replicas = models.PositiveIntegerField(default=1)
    cpu = models.CharField(max_length=32, default="100m")
    memory = models.CharField(max_length=32, default="128Mi")
    state = models.CharField(
        max_length=20,
        choices=AppState.choices,
        default=AppState.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["namespace", "name"],
                name="unique_app_per_namespace",
            )
        ]

    def __str__(self):
        return f"{self.id} - {self.name}"