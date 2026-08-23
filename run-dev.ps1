$projectPath = Get-Location

Write-Host "Starting Django server..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$projectPath'; .\venv\Scripts\activate; python manage.py runserver 0.0.0.0:8000"

Start-Sleep -Seconds 10

Write-Host "Starting Celery worker..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$projectPath'; .\venv\Scripts\activate; celery -A config worker --loglevel=INFO --pool=solo"

Write-Host "Starting Celery beat..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$projectPath'; .\venv\Scripts\activate; celery -A config beat --loglevel=INFO"

Start-Sleep -Seconds 3

Write-Host "Starting Kubernetes reconciler..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$projectPath'; .\venv\Scripts\activate; python manage.py reconcile --loop --interval 30"

Write-Host "All services started."