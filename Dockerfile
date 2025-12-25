# Image Python officielle légère
FROM python:3.11-slim

# Empêche le buffering des logs (utile sur Render)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Dossier de travail
WORKDIR /app

# Dépendances système nécessaires à psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier les dépendances Python
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste de l’application
COPY . .

# Port utilisé par Render
EXPOSE 10000

# Commande de démarrage (Render définit $PORT)
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-10000}"]
