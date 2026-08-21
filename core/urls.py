from django.urls import path

from .views import (
    AppDetailView,
    AppListCreateView,
    ClusterListCreateView,
    NamespaceDeleteView,
    NamespaceListCreateView,
    BackupView,
    
)

urlpatterns = [
    path("clusters/", ClusterListCreateView.as_view()),
    path("namespaces/", NamespaceListCreateView.as_view()),
    path("namespaces/<int:pk>/", NamespaceDeleteView.as_view()),
    path("apps/", AppListCreateView.as_view()),
    path("apps/<int:pk>/", AppDetailView.as_view()),
    path("backup/", BackupView.as_view()),
]