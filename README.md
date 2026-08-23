# Django Kubernetes Management Platform

A backend service built with Django and Django REST Framework designed to manage Kubernetes resources (Clusters, Namespaces, and Applications) and handle asynchronous backup operations using Celery.

## Disclaimer

This project is intended for educational, development, and demonstration purposes. It is not production-ready and should not be deployed in a production environment without implementing the security, reliability, storage, and operational controls described in the [Limitations and Production Readiness](#limitations-and-production-readiness) section.

## Architecture

The system relies on a standard Django web framework with a decoupled task queue for asynchronous operations.

- **Backend:** Django 6.1, Django REST Framework
- **Task Queue:** Celery with Redis as the message broker
- **Database:** SQLite (default for local development)
- **Infrastructure Integration:** Official Kubernetes Python Client (for cluster/namespace/app management) and `kubectl` subprocess (for backup operations)
- **Caching:** Redis (for caching live application status)

**Deployment Environments:**
While the setup guide below focuses on a Windows host (for Django/Celery) with WSL2 (for Redis via Docker), this architecture is OS-agnostic. It can be deployed on any Linux, macOS, or Windows environment where Python, `kubectl`, a running Redis instance, and network access to a Kubernetes API server are available.

## Setup and Installation

### Prerequisites
- Python 3.10 or higher
- Docker (for running Redis locally) or an existing Redis instance
- `kubectl` installed and available in PATH (required for backup operations)
- Access to a Kubernetes cluster (optional; the system includes a mock fallback for local testing without a live cluster)

### 1. Install kubectl

**Windows (via winget):**
```powershell
winget install Kubernetes.kubectl
```

**Linux/macOS:**
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
```

Verify installation:
```bash
kubectl version --client
```

### 2. Start Redis Broker
If using Docker, start a local Redis container:
```bash
docker run -d --name django-k8s-redis -p 6379:6379 redis:7-alpine
```

### 3. Install Dependencies
Create and activate a virtual environment, then install the required packages:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Initialize Database
Apply the database migrations to set up the local SQLite database:
```bash
python manage.py migrate
```

### 5. Start Services

**Option A: Automated (Windows PowerShell)**
Use the provided script to start all services in separate terminals:
```powershell
.\run-dev.ps1
```

**Option B: Manual (Separate Terminals)**
The platform requires multiple processes to run concurrently. Open separate terminal windows for each:

**Terminal 1: Django API Server**
```bash
python manage.py runserver 0.0.0.0:8000
```

**Terminal 2: Celery Worker**
The worker processes asynchronous tasks (like backups). The `--pool=solo` flag is required for Windows environments to avoid multiprocessing conflicts.
```bash
celery -A config worker --loglevel=INFO --pool=solo
```

**Terminal 3: Celery Beat**
The beat scheduler handles periodic tasks (backup schedules, cleanup).
```bash
celery -A config beat --loglevel=INFO
```

**Terminal 4: Kubernetes Reconciler (Optional)**
A background management command that periodically checks the actual state of Kubernetes resources and updates the database to match.
```bash
python manage.py reconcile --loop --interval 30
```

---

## Features and API Reference

The API is accessible at `http://127.0.0.1:8000/api/v1/`.

### 1. Cluster Management
Manages connections to different Kubernetes clusters. Authentication tokens are encrypted at rest using Fernet symmetric encryption and never exposed in API responses or logs.
- `POST /clusters/` - Register a new cluster (requires name, address, and token).
- `GET /clusters/` - List all registered clusters.

### 2. Namespace Management
Creates and deletes Kubernetes namespaces mapped to specific clusters.
- `POST /namespaces/` - Create a namespace (requires `cluster_id` and `name`).
- `GET /namespaces/?cluster_id=<id>` - List namespaces for a specific cluster.
- `DELETE /namespaces/<id>/` - Delete a namespace (only if it contains no apps).

### 3. Application Management
Manages Kubernetes Deployments. Creating, updating, or deleting an app via the API triggers the corresponding Kubernetes API calls.
- `POST /apps/` - Deploy a new application.
- `GET /apps/?namespace_id=<id>` - List apps in a namespace (includes live pod status).
- `GET /apps/<id>/` - Get detailed status of an application.
- `PATCH /apps/<id>/` - Update application resources (image, replicas, CPU, memory).
- `DELETE /apps/<id>/` - Remove the application and its Kubernetes deployment.

### 4. Backup System
Handles asynchronous file extraction from running pods using `kubectl exec` via subprocess.
- `POST /backup/` - Trigger an instant backup or schedule a recurring one using a cron expression.
- `GET /backup/?app_id=<id>` - List all backup records for an app.
- `GET /backup/<backup_id>/` - Check the status of a specific backup task.

**Backup Implementation Details:**
- Backups are executed via `kubectl exec` subprocess with explicit `--server`, `--token`, and `--insecure-skip-tls-verify` flags
- Output is compressed as a valid `tar.gz` archive (tar inside gzip)
- Timeout protection prevents token exposure in error logs
- Files are stored in `/backups/{app_id}/{yyyy-mm-dd}/{backup_id}.tar.gz`

### 5. Reconciler
A standalone management command (`python manage.py reconcile`) that detects drift between the database state and the actual Kubernetes cluster state. It handles stuck states (e.g., `CREATE_FAILED`, `DELETING`) and updates the database accordingly.

---

## Testing the Features

Use an HTTP client (Postman, Insomnia, or `curl`) to test the workflow.

### Step 1: Setup Base Resources
```bash
curl -X POST http://127.0.0.1:8000/api/v1/clusters/ \
  -H "Content-Type: application/json" \
  -d '{"name": "k3s-local", "address": "94.101.184.38:6443", "token": "YOUR_K3S_TOKEN"}'

curl -X POST http://127.0.0.1:8000/api/v1/namespaces/ \
  -H "Content-Type: application/json" \
  -d '{"cluster_id": 1, "name": "test-ns"}'
```

### Step 2: Deploy an Application
```bash
curl -X POST http://127.0.0.1:8000/api/v1/apps/ \
  -H "Content-Type: application/json" \
  -d '{"namespace_id": 1, "name": "nginx-app", "image": "nginx:alpine", "replicas": 2, "cpu": "100m", "memory": "128Mi"}'
```

### Step 3: Trigger an Instant Backup
**Important:** Use real files inside the pod, not symlinks to stdout/stderr.
```bash
# First, create a test file in the pod
kubectl exec -n test-ns nginx-app-<pod-id> -- sh -c 'echo "test data" > /tmp/test-backup.txt'

# Then backup it
curl -X POST http://127.0.0.1:8000/api/v1/backup/ \
  -H "Content-Type: application/json" \
  -d '{"app_id": 1, "source_path": "/tmp/test-backup.txt"}'
```
Check the Celery worker terminal to see the task execution. If the K8s API is unreachable, the worker will generate a mock archive locally to complete the task pipeline.

### Step 4: Schedule a Periodic Backup
```bash
curl -X POST http://127.0.0.1:8000/api/v1/backup/ \
  -H "Content-Type: application/json" \
  -d '{"app_id": 1, "source_path": "/tmp/test-backup.txt", "schedule": "* * * * *"}'
```
Watch the Celery Beat logs; a new backup task will be dispatched every minute.

### Step 5: Test the Reconciler
If you manually delete a deployment via `kubectl` (or if a cluster is temporarily down), run `python manage.py reconcile` once. The app's state in the database should update to reflect the actual cluster state (e.g., changing from `ACTIVE` to `MISSING`).

---

## Limitations and Production Readiness

This codebase is structured for local development and functional demonstration. Several components require modifications before being deployed to a production environment.

- **Database Engine:** The project uses SQLite by default. Production deployments should configure PostgreSQL or MySQL for concurrent write handling and data durability.
- **Backup Mechanism:** Backups are extracted using `kubectl exec cat` inside the target pod. This approach:
  - Is inefficient for large files (>100MB)
  - Does not guarantee data consistency for active databases
  - Cannot handle symlinks to stdout/stderr (e.g., `/var/log/nginx/access.log` in containerized nginx)
  - Production systems should use volume snapshots, storage-level replication, or database-native dump utilities
- **Storage Destination:** Backup archives are saved to the local filesystem of the Celery worker node. In a distributed production environment, backups must be streamed to durable object storage (e.g., AWS S3, MinIO, GCS).
- **Security Controls:** The API currently permits unauthenticated access (`AllowAny`). Production implementations require JWT/OAuth2 authentication, role-based access control (RBAC), and strict CORS policies.
- **TLS Verification:** SSL verification is disabled for Kubernetes API calls to simplify local testing against self-signed certificates (e.g., k3s, minikube). Production configurations must enforce strict TLS verification.
- **Celery Concurrency:** The worker is configured with `--pool=solo` to ensure compatibility with Windows. Production Linux environments should use `prefork`, `gevent`, or `eventlet` pools to process tasks concurrently.
- **Cache Invalidation:** The Redis cache for app status uses a fixed 60-second TTL. It does not actively invalidate when an app is updated or deleted via the API, which may result in serving stale data for up to a minute.
- **Alerting:** The system logs failed tasks and stale backups but lacks an active notification system (e.g., PagerDuty, Slack, or Email alerts) for operational failures.
- **kubectl Dependency:** Backup operations require `kubectl` to be installed and available in PATH on the worker node. Containerized deployments should include `kubectl` in the worker image.