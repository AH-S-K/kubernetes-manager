from django import forms
from django.contrib import admin

from .models import App, Backup, BackupSchedule, Cluster, Namespace
from .services.crypto import encrypt_secret


class ClusterAdminForm(forms.ModelForm):
    token = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        label="Kubernetes Token",
        help_text="Enter a new value to create or update the token. If left blank, the existing token will be preserved."
    )

    class Meta:
        model = Cluster
        fields = ["name", "address", "ca_cert"]


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    form = ClusterAdminForm
    list_display = ["id", "name", "address", "created_at"]
    search_fields = ["name", "address"]

    def save_model(self, request, obj, form, change):
        token = form.cleaned_data.get("token")
        if token:
            obj.token_encrypted = encrypt_secret(token)
        super().save_model(request, obj, form, change)


@admin.register(Namespace)
class NamespaceAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "cluster", "state", "created_at"]
    list_filter = ["state", "cluster"]
    search_fields = ["name"]


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "namespace", "image", "replicas", "state"]
    list_filter = ["state"]
    search_fields = ["name", "namespace__name"]


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ["backup_id", "app", "status", "created_at"]
    list_filter = ["status"]


@admin.register(BackupSchedule)
class BackupScheduleAdmin(admin.ModelAdmin):
    list_display = ["id", "app", "is_active", "created_at"]
    list_filter = ["is_active"]