<<<<<<< HEAD
# UX-Manager-backlogs
=======
# UX Manager – Plataforma de reseñas y selección

Este repositorio contiene el bootstrap del proyecto con Django 5, DRF, Allauth, HTMX, Redis cache y Postgres.

## Instalación (local)

1) Python 3.12 y virtualenv:

```
python -m venv .venv
./.venv/Scripts/Activate.ps1  # Windows PowerShell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Postgres y Redis (Docker):

```
docker compose up -d
```

3) Variables de entorno:

```
copy .env.example .env
# Edita .env según tus credenciales si aplica
```

4) Migraciones y arranque:

```
python manage.py migrate
python manage.py runserver
```

5) Tests:

```
pytest
```

## Tailwind

Se usa CDN de Tailwind para desarrollo rápido. En producción se recomienda compilar con CLI y servir CSS estático.

>>>>>>> 247b608 (Primer commit, base del código)
