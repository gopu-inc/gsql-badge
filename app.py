"""
Zenv Package Hub - Plateforme complète avec PostgreSQL et branche package GitHub
"""

import os
import json
import hashlib
import base64
import secrets
import jwt
import bcrypt
import subprocess
import tempfile
import shutil
import tarfile
import zipfile
import io
import uuid
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file, abort
from flask_cors import CORS
import markdown
import yaml
from packaging.version import parse as parse_version

# ============================================================================
# CONFIGURATION GITHUB
# ============================================================================

GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "package"  # Branche spécifique pour les packages

# ============================================================================
# CONFIGURATION POSTGRESQL
# ============================================================================

DATABASE_URL = "postgresql://volve_user:odM5spc4DLMdEPJww834aDNE7c49J9bG@dpg-d4vpeu24d50c7385s840-a.oregon-postgres.render.com/volve?sslmode=require"

# ============================================================================
# CONFIGURATION FLASK
# ============================================================================

app = Flask(__name__)
CORS(app)

app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', secrets.token_hex(32)),
    JWT_SECRET_KEY=os.environ.get('JWT_SECRET_KEY', secrets.token_hex(32)),
    DATABASE_URL=DATABASE_URL,
    PACKAGE_DIR=os.path.join(os.path.dirname(__file__), 'packages'),
    UPLOAD_DIR=os.path.join(os.path.dirname(__file__), 'uploads'),
    BUILD_DIR=os.path.join(os.path.dirname(__file__), 'builds'),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=24),
    JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=30),
    BCRYPT_ROUNDS=12
)

# Créer les répertoires
for dir_path in [app.config['PACKAGE_DIR'], app.config['UPLOAD_DIR'], app.config['BUILD_DIR']]:
    os.makedirs(dir_path, exist_ok=True)

# ============================================================================
# CONNEXION POSTGRESQL
# ============================================================================

def get_db_connection():
    """Établit une connexion à PostgreSQL"""
    try:
        conn = psycopg2.connect(app.config['DATABASE_URL'])
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise

def init_postgresql():
    """Initialise les tables PostgreSQL"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Table des utilisateurs
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role VARCHAR(20) DEFAULT 'user',
                github_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_verified BOOLEAN DEFAULT FALSE,
                verification_token TEXT,
                reset_token TEXT,
                reset_expires TIMESTAMP,
                last_login TIMESTAMP,
                CONSTRAINT valid_role CHECK (role IN ('user', 'admin', 'moderator'))
            )
        ''')
        
        # Table des packages
        cur.execute('''
            CREATE TABLE IF NOT EXISTS packages (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                version VARCHAR(50) NOT NULL,
                author VARCHAR(100),
                author_email VARCHAR(100),
                license VARCHAR(50),
                keywords TEXT[],
                python_requires VARCHAR(50),
                dependencies JSONB,
                readme TEXT,
                github_url VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                downloads_count INTEGER DEFAULT 0,
                is_private BOOLEAN DEFAULT FALSE,
                UNIQUE(name, version)
            )
        ''')
        
        # Table des releases
        cur.execute('''
            CREATE TABLE IF NOT EXISTS releases (
                id SERIAL PRIMARY KEY,
                package_id INTEGER REFERENCES packages(id) ON DELETE CASCADE,
                version VARCHAR(50) NOT NULL,
                filename VARCHAR(200),
                file_size BIGINT,
                file_hash VARCHAR(64),
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                download_count INTEGER DEFAULT 0,
                github_release_id VARCHAR(100),
                lfs_tracked BOOLEAN DEFAULT FALSE,
                UNIQUE(package_id, version)
            )
        ''')
        
        # Table des téléchargements
        cur.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id SERIAL PRIMARY KEY,
                release_id INTEGER REFERENCES releases(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                ip_address INET,
                user_agent TEXT,
                country VARCHAR(50),
                download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                api_key VARCHAR(100)
            )
        ''')
        
        # Table des tokens API
        cur.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                key_hash VARCHAR(64) UNIQUE NOT NULL,
                name VARCHAR(100),
                scopes TEXT[],
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMP
            )
        ''')
        
        # Table des associations (organisations)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Table des membres d'organisation
        cur.execute('''
            CREATE TABLE IF NOT EXISTS organization_members (
                id SERIAL PRIMARY KEY,
                organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                role VARCHAR(20) DEFAULT 'member',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(organization_id, user_id)
            )
        ''')
        
        # Table des statistiques
        cur.execute('''
            CREATE TABLE IF NOT EXISTS stats_daily (
                id SERIAL PRIMARY KEY,
                date DATE UNIQUE NOT NULL,
                total_downloads INTEGER DEFAULT 0,
                unique_downloaders INTEGER DEFAULT 0,
                new_packages INTEGER DEFAULT 0,
                new_users INTEGER DEFAULT 0
            )
        ''')
        
        # Index pour les performances
        cur.execute('CREATE INDEX IF NOT EXISTS idx_packages_name ON packages(name)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_packages_user_id ON packages(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_releases_package_id ON releases(package_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_downloads_release_id ON downloads(release_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_downloads_download_time ON downloads(download_time)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)')
        
        conn.commit()
        print("PostgreSQL tables initialized successfully")
        
    except Exception as e:
        conn.rollback()
        print(f"Error initializing PostgreSQL: {e}")
        raise
    finally:
        cur.close()
        conn.close()

# ============================================================================
# UTILITAIRES DE SÉCURITÉ AMÉLIORÉS
# ============================================================================

def hash_sha512_salt(data: str, salt: str = None) -> tuple:
    """Hash SHA512 avec salt"""
    if not salt:
        salt = secrets.token_hex(16)
    combined = salt + data
    hash_obj = hashlib.sha512()
    hash_obj.update(combined.encode())
    return salt, hash_obj.hexdigest()

def encrypt_data(data: str, key: str = None) -> str:
    """Chiffrement simple pour les tokens"""
    if not key:
        key = app.config['SECRET_KEY']
    salt = secrets.token_hex(8)
    combined = salt + data + key
    hash_result = hashlib.sha512(combined.encode()).hexdigest()
    return base64.b64encode(f"{salt}:{hash_result}".encode()).decode()

def verify_encrypted(data: str, encrypted: str, key: str = None) -> bool:
    """Vérifie les données chiffrées"""
    if not key:
        key = app.config['SECRET_KEY']
    try:
        decoded = base64.b64decode(encrypted.encode()).decode()
        salt, stored_hash = decoded.split(':')
        combined = salt + data + key
        computed_hash = hashlib.sha512(combined.encode()).hexdigest()
        return hmac.compare_digest(computed_hash, stored_hash)
    except:
        return False

def hash_password_secure(password: str) -> tuple:
    """Hash password avec multiple couches de sécurité"""
    # Couche 1: SHA256
    sha256_hash = hashlib.sha256(password.encode()).hexdigest()
    
    # Couche 2: bcrypt
    salt = bcrypt.gensalt(rounds=app.config['BCRYPT_ROUNDS'])
    bcrypt_hash = bcrypt.hashpw(sha256_hash.encode(), salt)
    
    # Couche 3: SHA512 + salt
    final_salt, final_hash = hash_sha512_salt(bcrypt_hash.decode())
    
    return final_salt, final_hash

def verify_password_secure(password: str, salt: str, stored_hash: str) -> bool:
    """Vérifie le password sécurisé"""
    try:
        # Reconstruire le hash
        sha256_hash = hashlib.sha256(password.encode()).hexdigest()
        test_hash = hashlib.sha512()
        test_hash.update(salt.encode())
        test_hash.update(sha256_hash.encode())
        test_result = test_hash.hexdigest()
        
        return hmac.compare_digest(test_result, stored_hash)
    except:
        return False

def generate_api_key(user_id: int, name: str = "Default") -> str:
    """Génère une clé API sécurisée"""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO api_keys (user_id, key_hash, name) VALUES (%s, %s, %s) RETURNING id',
            (user_id, key_hash, name)
        )
        conn.commit()
        return raw_key
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

# ============================================================================
# UTILITAIRES GITHUB AMÉLIORÉS
# ============================================================================

def setup_git_lfs():
    """Configure Git LFS pour les fichiers binaires"""
    try:
        # Initialiser Git LFS
        subprocess.run(['git', 'lfs', 'install'], check=True)
        
        # Track les fichiers binaires typiques des packages Python
        lfs_patterns = ['*.whl', '*.tar.gz', '*.zip', '*.egg', '*.so', '*.pyd']
        
        for pattern in lfs_patterns:
            subprocess.run(['git', 'lfs', 'track', pattern], check=True)
        
        # Ajouter .gitattributes
        with open('.gitattributes', 'a') as f:
            f.write('\n' + '\n'.join([f'{pattern} filter=lfs diff=lfs merge=lfs -text' for pattern in lfs_patterns]))
        
        return True
    except Exception as e:
        print(f"Git LFS setup error: {e}")
        return False

def auto_commit_to_github(package_path: str, version: str, commit_message: str = None):
    """Commit automatique vers GitHub sur la branche package"""
    try:
        if not commit_message:
            commit_message = f"📦 Release {version} - Auto-generated by Zenv Package Hub"
        
        # Cloner le repo temporairement
        temp_dir = tempfile.mkdtemp()
        repo_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        
        # Cloner avec la branche package
        subprocess.run(['git', 'clone', '-b', GITHUB_BRANCH, repo_url, temp_dir], 
                      check=True, capture_output=True)
        
        # Se déplacer dans le repo
        os.chdir(temp_dir)
        
        # Configurer Git
        subprocess.run(['git', 'config', 'user.name', GITHUB_USERNAME], check=True)
        subprocess.run(['git', 'config', 'user.email', GITHUB_EMAIL], check=True)
        
        # Configurer LFS
        setup_git_lfs()
        
        # Créer la structure de dossiers
        releases_dir = os.path.join(temp_dir, 'releases', version)
        os.makedirs(releases_dir, exist_ok=True)
        
        # Copier les fichiers du package
        for item in os.listdir(package_path):
            src = os.path.join(package_path, item)
            dst = os.path.join(releases_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            else:
                shutil.copytree(src, dst, dirs_exist_ok=True)
        
        # Ajouter et commiter
        subprocess.run(['git', 'add', '.'], check=True)
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        
        # Pusher sur la branche package
        subprocess.run(['git', 'push', 'origin', GITHUB_BRANCH], check=True)
        
        # Nettoyer
        os.chdir('/')
        shutil.rmtree(temp_dir)
        
        # Créer un GitHub Release
        create_github_release(version, commit_message, releases_dir)
        
        return True
    except Exception as e:
        print(f"GitHub auto-commit error: {e}")
        return False

def create_github_release(version: str, message: str, assets_dir: str):
    """Crée un GitHub Release avec les assets"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
        
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        data = {
            'tag_name': f'v{version}',
            'target_commitish': GITHUB_BRANCH,
            'name': f'Version {version}',
            'body': message,
            'draft': False,
            'prerelease': False
        }
        
        # Créer le release
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 201:
            release_data = response.json()
            release_id = release_data['id']
            
            # Uploader les assets
            for filename in os.listdir(assets_dir):
                if filename.endswith(('.whl', '.tar.gz', '.zip')):
                    asset_path = os.path.join(assets_dir, filename)
                    upload_asset_to_release(release_id, asset_path)
            
            return release_id
    except Exception as e:
        print(f"GitHub release creation error: {e}")
        return None

def upload_asset_to_release(release_id: str, asset_path: str):
    """Upload un asset sur GitHub Release"""
    try:
        filename = os.path.basename(asset_path)
        url = f"https://uploads.github.com/repos/{GITHUB_REPO}/releases/{release_id}/assets?name={filename}"
        
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Content-Type': 'application/octet-stream'
        }
        
        with open(asset_path, 'rb') as f:
            response = requests.post(url, headers=headers, data=f)
        
        return response.status_code == 201
    except Exception as e:
        print(f"Asset upload error: {e}")
        return False

# ============================================================================
# UTILITAIRES DE PACKAGE
# ============================================================================

def extract_package_metadata(package_path: str) -> dict:
    """Extrait les métadonnées d'un package Python"""
    metadata = {
        'name': 'unknown',
        'version': '0.0.0',
        'author': 'Unknown',
        'email': '',
        'license': 'MIT',
        'description': '',
        'requires_python': '>=3.6',
        'dependencies': []
    }
    
    try:
        # Chercher setup.py
        setup_py = os.path.join(package_path, 'setup.py')
        if os.path.exists(setup_py):
            with open(setup_py, 'r') as f:
                content = f.read()
                
                # Extraction simple (pour une vraie implémentation, utiliser ast)
                import re
                
                # Nom
                name_match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", content)
                if name_match:
                    metadata['name'] = name_match.group(1)
                
                # Version
                version_match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
                if version_match:
                    metadata['version'] = version_match.group(1)
                
                # Author
                author_match = re.search(r"author\s*=\s*['\"]([^'\"]+)['\"]", content)
                if author_match:
                    metadata['author'] = author_match.group(1)
                
                # Email
                email_match = re.search(r"author_email\s*=\s*['\"]([^'\"]+)['\"]", content)
                if email_match:
                    metadata['email'] = email_match.group(1)
        
        # Chercher pyproject.toml
        pyproject_toml = os.path.join(package_path, 'pyproject.toml')
        if os.path.exists(pyproject_toml):
            try:
                import tomli
                with open(pyproject_toml, 'rb') as f:
                    toml_data = tomli.load(f)
                    
                if 'project' in toml_data:
                    project = toml_data['project']
                    metadata['name'] = project.get('name', metadata['name'])
                    metadata['version'] = project.get('version', metadata['version'])
                    metadata['description'] = project.get('description', metadata['description'])
                    metadata['requires_python'] = project.get('requires-python', metadata['requires_python'])
                    
                    if 'authors' in project and project['authors']:
                        metadata['author'] = project['authors'][0].get('name', metadata['author'])
                        metadata['email'] = project['authors'][0].get('email', metadata['email'])
                    
                    if 'dependencies' in project:
                        metadata['dependencies'] = project['dependencies']
            except:
                pass
        
        # Lire README
        readme_paths = [
            os.path.join(package_path, 'README.md'),
            os.path.join(package_path, 'README.rst'),
            os.path.join(package_path, 'README.txt'),
        ]
        
        for readme_path in readme_paths:
            if os.path.exists(readme_path):
                with open(readme_path, 'r', encoding='utf-8') as f:
                    metadata['readme'] = f.read()
                break
        
    except Exception as e:
        print(f"Metadata extraction error: {e}")
    
    return metadata

def build_package_distributions(package_path: str, version: str) -> dict:
    """Construit les distributions du package (.tar.gz et .whl)"""
    build_dir = os.path.join(app.config['BUILD_DIR'], f"{os.path.basename(package_path)}-{version}")
    os.makedirs(build_dir, exist_ok=True)
    
    result = {
        'sdist': None,
        'wheel': None,
        'build_dir': build_dir
    }
    
    try:
        # Copier les fichiers sources
        temp_build = tempfile.mkdtemp()
        shutil.copytree(package_path, os.path.join(temp_build, os.path.basename(package_path)), 
                       dirs_exist_ok=True)
        
        # Construire les distributions
        os.chdir(temp_build)
        
        # Sdist (.tar.gz)
        sdist_cmd = ['python', '-m', 'build', '--sdist']
        subprocess.run(sdist_cmd, check=True, capture_output=True)
        
        # Wheel (.whl)
        wheel_cmd = ['python', '-m', 'build', '--wheel']
        subprocess.run(wheel_cmd, check=True, capture_output=True)
        
        # Trouver les fichiers générés
        dist_dir = os.path.join(temp_build, 'dist')
        if os.path.exists(dist_dir):
            for filename in os.listdir(dist_dir):
                src = os.path.join(dist_dir, filename)
                dst = os.path.join(build_dir, filename)
                shutil.copy2(src, dst)
                
                if filename.endswith('.tar.gz'):
                    result['sdist'] = dst
                elif filename.endswith('.whl'):
                    result['wheel'] = dst
        
        # Nettoyer
        os.chdir('/')
        shutil.rmtree(temp_build)
        
    except Exception as e:
        print(f"Package build error: {e}")
    
    return result

# ============================================================================
# ROUTES D'AUTHENTIFICATION
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute('SELECT id, username, password, salt, role FROM users WHERE username = %s OR email = %s', 
                       (username, username))
            user = cur.fetchone()
            
            if user and verify_password_secure(password, user['salt'], user['password']):
                # Mettre à jour la dernière connexion
                cur.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s', (user['id'],))
                conn.commit()
                
                # Générer les tokens
                tokens = generate_jwt(user['id'], user['role'])
                
                # Stocker dans la session
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['access_token'] = tokens['access_token']
                
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Identifiants incorrects', 'danger')
                
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Page d'inscription"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html')
        
        if len(password) < 8:
            flash('Le mot de passe doit faire au moins 8 caractères', 'danger')
            return render_template('register.html')
        
        # Hasher le mot de passe
        salt, hashed_password = hash_password_secure(password)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute(
                'INSERT INTO users (username, email, password, salt) VALUES (%s, %s, %s, %s) RETURNING id',
                (username, email, hashed_password, salt)
            )
            user_id = cur.fetchone()['id']
            conn.commit()
            
            flash('Inscription réussie! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('login'))
            
        except psycopg2.IntegrityError as e:
            conn.rollback()
            if 'username' in str(e):
                flash('Ce nom d\'utilisateur existe déjà', 'danger')
            elif 'email' in str(e):
                flash('Cet email est déjà utilisé', 'danger')
            else:
                flash('Erreur lors de l\'inscription', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'Erreur: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('index'))

# ============================================================================
# ROUTES DU DASHBOARD
# ============================================================================

@app.route('/dashboard')
def dashboard():
    """Dashboard utilisateur"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Récupérer les infos utilisateur
        cur.execute('SELECT username, email, role, created_at FROM users WHERE id = %s', 
                   (session['user_id'],))
        user = cur.fetchone()
        
        # Récupérer les packages de l'utilisateur
        cur.execute('''
            SELECT p.*, COUNT(r.id) as release_count, SUM(r.download_count) as total_downloads
            FROM packages p
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.user_id = %s
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            LIMIT 10
        ''', (session['user_id'],))
        packages = cur.fetchall()
        
        # Statistiques
        cur.execute('''
            SELECT 
                COUNT(DISTINCT p.id) as total_packages,
                COUNT(r.id) as total_releases,
                COALESCE(SUM(r.download_count), 0) as total_downloads
            FROM packages p
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.user_id = %s
        ''', (session['user_id'],))
        stats = cur.fetchone()
        
        # Derniers téléchargements
        cur.execute('''
            SELECT d.*, p.name as package_name, r.version as release_version
            FROM downloads d
            JOIN releases r ON d.release_id = r.id
            JOIN packages p ON r.package_id = p.id
            WHERE d.user_id = %s
            ORDER BY d.download_time DESC
            LIMIT 5
        ''', (session['user_id'],))
        recent_downloads = cur.fetchall()
        
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
        user = {}
        packages = []
        stats = {}
        recent_downloads = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('dashboard.html', 
                         user=user, 
                         packages=packages, 
                         stats=stats, 
                         recent_downloads=recent_downloads)

# ============================================================================
# ROUTES DE GESTION DES PACKAGES
# ============================================================================

@app.route('/package/upload', methods=['GET', 'POST'])
def upload_package():
    """Upload d'un package"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'package' not in request.files:
            flash('Aucun fichier sélectionné', 'danger')
            return render_template('upload.html')
        
        file = request.files['package']
        if file.filename == '':
            flash('Aucun fichier sélectionné', 'danger')
            return render_template('upload.html')
        
        # Vérifier l'extension
        allowed_extensions = {'.zip', '.tar.gz', '.whl'}
        file_ext = os.path.splitext(file.filename)[1]
        if file.filename.endswith('.tar.gz'):
            file_ext = '.tar.gz'
        
        if file_ext not in allowed_extensions:
            flash('Format de fichier non supporté', 'danger')
            return render_template('upload.html')
        
        # Sauvegarder temporairement
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, file.filename)
        file.save(temp_path)
        
        # Extraire si c'est une archive
        extract_dir = os.path.join(temp_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)
        
        try:
            if file_ext == '.zip':
                with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif file_ext == '.tar.gz':
                with tarfile.open(temp_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_dir)
            else:  # .whl
                shutil.copy(temp_path, extract_dir)
            
            # Trouver le setup.py ou pyproject.toml
            package_root = None
            for root, dirs, files in os.walk(extract_dir):
                if 'setup.py' in files or 'pyproject.toml' in files:
                    package_root = root
                    break
            
            if not package_root:
                flash('Aucun package Python valide trouvé', 'danger')
                shutil.rmtree(temp_dir)
                return render_template('upload.html')
            
            # Extraire les métadonnées
            metadata = extract_package_metadata(package_root)
            
            # Construire les distributions
            builds = build_package_distributions(package_root, metadata['version'])
            
            # Sauvegarder dans le dossier permanent
            permanent_dir = os.path.join(app.config['PACKAGE_DIR'], 
                                        f"{metadata['name']}-{metadata['version']}")
            os.makedirs(permanent_dir, exist_ok=True)
            
            for item in os.listdir(builds['build_dir']):
                src = os.path.join(builds['build_dir'], item)
                dst = os.path.join(permanent_dir, item)
                shutil.copy2(src, dst)
            
            # Enregistrer dans la base de données
            conn = get_db_connection()
            cur = conn.cursor()
            
            try:
                # Vérifier si le package existe déjà
                cur.execute('SELECT id FROM packages WHERE name = %s', (metadata['name'],))
                existing = cur.fetchone()
                
                if existing:
                    # Mettre à jour le package existant
                    cur.execute('''
                        UPDATE packages 
                        SET version = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        RETURNING id
                    ''', (metadata['version'], metadata['description'], existing['id']))
                    package_id = existing['id']
                else:
                    # Créer un nouveau package
                    cur.execute('''
                        INSERT INTO packages 
                        (name, version, description, author, author_email, license, 
                         python_requires, dependencies, readme, user_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (
                        metadata['name'], metadata['version'], metadata['description'],
                        metadata['author'], metadata['email'], metadata['license'],
                        metadata['requires_python'], json.dumps(metadata['dependencies']),
                        metadata.get('readme', ''), session['user_id']
                    ))
                    package_id = cur.fetchone()['id']
                
                # Enregistrer les releases
                for build_type, build_path in [('sdist', builds['sdist']), ('wheel', builds['wheel'])]:
                    if build_path and os.path.exists(build_path):
                        filename = os.path.basename(build_path)
                        file_size = os.path.getsize(build_path)
                        
                        # Calculer le hash
                        with open(build_path, 'rb') as f:
                            file_hash = hashlib.sha256(f.read()).hexdigest()
                        
                        cur.execute('''
                            INSERT INTO releases 
                            (package_id, version, filename, file_size, file_hash)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (package_id, version) DO UPDATE 
                            SET filename = EXCLUDED.filename,
                                file_size = EXCLUDED.file_size,
                                file_hash = EXCLUDED.file_hash
                        ''', (package_id, metadata['version'], filename, file_size, file_hash))
                
                conn.commit()
                
                # Auto-commit vers GitHub
                if auto_commit_to_github(permanent_dir, metadata['version']):
                    flash('Package uploadé et publié sur GitHub avec succès!', 'success')
                else:
                    flash('Package uploadé, mais erreur lors de la publication GitHub', 'warning')
                
                return redirect(url_for('package_view', package_name=metadata['name']))
                
            except Exception as e:
                conn.rollback()
                flash(f'Erreur base de données: {str(e)}', 'danger')
            finally:
                cur.close()
                conn.close()
            
        except Exception as e:
            flash(f'Erreur traitement package: {str(e)}', 'danger')
        finally:
            # Nettoyer les fichiers temporaires
            shutil.rmtree(temp_dir)
    
    return render_template('upload.html')

@app.route('/package/<package_name>')
def package_view(package_name):
    """Page de visualisation d'un package"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Récupérer le package
        cur.execute('''
            SELECT p.*, u.username as owner_username,
                   COUNT(r.id) as release_count,
                   COALESCE(SUM(r.download_count), 0) as total_downloads
            FROM packages p
            LEFT JOIN users u ON p.user_id = u.id
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.name = %s
            GROUP BY p.id, u.id
        ''', (package_name,))
        package = cur.fetchone()
        
        if not package:
            flash('Package non trouvé', 'danger')
            return redirect(url_for('dashboard'))
        
        # Récupérer les releases
        cur.execute('''
            SELECT * FROM releases 
            WHERE package_id = %s 
            ORDER BY upload_date DESC
        ''', (package['id'],))
        releases = cur.fetchall()
        
        # Convertir README en HTML
        readme_html = ''
        if package['readme']:
            if package['readme'].startswith('#'):  # Markdown
                readme_html = markdown.markdown(package['readme'], 
                                               extensions=['fenced_code', 'tables'])
            else:
                readme_html = f"<pre><code>{package['readme']}</code></pre>"
        
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        cur.close()
        conn.close()
    
    return render_template('package.html', 
                         package=package, 
                         releases=releases, 
                         readme_html=readme_html)

# ============================================================================
# ROUTES ADMIN
# ============================================================================

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Dashboard administrateur"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Statistiques globales
        cur.execute('''
            SELECT 
                COUNT(DISTINCT u.id) as total_users,
                COUNT(DISTINCT p.id) as total_packages,
                COUNT(DISTINCT r.id) as total_releases,
                COALESCE(SUM(r.download_count), 0) as total_downloads,
                COUNT(DISTINCT CASE WHEN u.created_at >= CURRENT_DATE - INTERVAL '7 days' THEN u.id END) as new_users_week,
                COUNT(DISTINCT CASE WHEN p.created_at >= CURRENT_DATE - INTERVAL '7 days' THEN p.id END) as new_packages_week
            FROM users u
            LEFT JOIN packages p ON u.id = p.user_id
            LEFT JOIN releases r ON p.id = r.package_id
        ''')
        stats = cur.fetchone()
        
        # Derniers utilisateurs
        cur.execute('''
            SELECT id, username, email, role, created_at 
            FROM users 
            ORDER BY created_at DESC 
            LIMIT 10
        ''')
        recent_users = cur.fetchall()
        
        # Derniers packages
        cur.execute('''
            SELECT p.*, u.username 
            FROM packages p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC 
            LIMIT 10
        ''')
        recent_packages = cur.fetchall()
        
        # Téléchargements récents
        cur.execute('''
            SELECT d.*, p.name as package_name, u.username as user_name
            FROM downloads d
            LEFT JOIN releases r ON d.release_id = r.id
            LEFT JOIN packages p ON r.package_id = p.id
            LEFT JOIN users u ON d.user_id = u.id
            ORDER BY d.download_time DESC
            LIMIT 20
        ''')
        recent_downloads = cur.fetchall()
        
    except Exception as e:
        flash(f'Erreur: {str(e)}', 'danger')
        stats = {}
        recent_users = []
        recent_packages = []
        recent_downloads = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('admin.html', 
                         stats=stats,
                         recent_users=recent_users,
                         recent_packages=recent_packages,
                         recent_downloads=recent_downloads)

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/v1/packages', methods=['GET'])
def api_list_packages():
    """API: Liste des packages"""
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 20)), 100)
    search = request.args.get('q', '')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = '''
            SELECT p.*, u.username as owner_username,
                   COUNT(r.id) as release_count,
                   COALESCE(SUM(r.download_count), 0) as total_downloads
            FROM packages p
            LEFT JOIN users u ON p.user_id = u.id
            LEFT JOIN releases r ON p.id = r.package_id
        '''
        
        params = []
        if search:
            query += ' WHERE p.name ILIKE %s OR p.description ILIKE %s'
            params.extend([f'%{search}%', f'%{search}%'])
        
        query += ' GROUP BY p.id, u.id ORDER BY p.updated_at DESC'
        
        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, offset])
        
        cur.execute(query, params)
        packages = cur.fetchall()
        
        # Total count
        count_query = 'SELECT COUNT(*) as total FROM packages'
        if search:
            count_query += ' WHERE name ILIKE %s OR description ILIKE %s'
            cur.execute(count_query, (f'%{search}%', f'%{search}%'))
        else:
            cur.execute(count_query)
        
        total = cur.fetchone()['total']
        
        return jsonify({
            'packages': packages,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/v1/package/<package_name>', methods=['GET'])
def api_get_package(package_name):
    """API: Détails d'un package"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT p.*, u.username as owner_username
            FROM packages p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.name = %s
        ''', (package_name,))
        
        package = cur.fetchone()
        
        if not package:
            return jsonify({'error': 'Package not found'}), 404
        
        # Récupérer les releases
        cur.execute('''
            SELECT * FROM releases 
            WHERE package_id = %s 
            ORDER BY version DESC
        ''', (package['id'],))
        releases = cur.fetchall()
        
        return jsonify({
            'package': package,
            'releases': releases
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/v1/download/<package_name>/<version>', methods=['GET'])
def api_download_package(package_name, version):
    """API: Télécharger un package"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Trouver le package
        cur.execute('SELECT id FROM packages WHERE name = %s', (package_name,))
        package = cur.fetchone()
        
        if not package:
            return jsonify({'error': 'Package not found'}), 404
        
        # Trouver la release
        cur.execute('''
            SELECT * FROM releases 
            WHERE package_id = %s AND version = %s
        ''', (package['id'], version))
        
        release = cur.fetchone()
        
        if not release:
            return jsonify({'error': 'Release not found'}), 404
        
        # Construire le chemin du fichier
        file_path = os.path.join(app.config['PACKAGE_DIR'], 
                                f"{package_name}-{version}", 
                                release['filename'])
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Enregistrer le téléchargement
        ip_address = request.remote_addr
        user_agent = request.user_agent.string
        
        cur.execute('''
            INSERT INTO downloads (release_id, ip_address, user_agent, download_time)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ''', (release['id'], ip_address, user_agent))
        
        # Mettre à jour le compteur
        cur.execute('''
            UPDATE releases 
            SET download_count = download_count + 1 
            WHERE id = %s
        ''', (release['id'],))
        
        cur.execute('''
            UPDATE packages 
            SET downloads_count = downloads_count + 1 
            WHERE id = %s
        ''', (package['id'],))
        
        conn.commit()
        
        # Retourner le fichier
        return send_file(file_path, as_attachment=True)
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ============================================================================
# GESTION DES ORGANISATIONS
# ============================================================================

@app.route('/organizations')
def list_organizations():
    """Liste des organisations"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT o.*, u.username as owner_name,
                   COUNT(DISTINCT om.user_id) as member_count,
                   COUNT(DISTINCT p.id) as package_count
            FROM organizations o
            LEFT JOIN users u ON o.owner_id = u.id
            LEFT JOIN organization_members om ON o.id = om.organization_id
            LEFT JOIN packages p ON o.id = p.user_id
            WHERE o.is_public = TRUE
            GROUP BY o.id, u.id
            ORDER BY o.created_at DESC
        ''')
        organizations = cur.fetchall()
    except Exception as e:
        organizations = []
        flash(f'Erreur: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return render_template('organizations.html', organizations=organizations)

@app.route('/organization/create', methods=['GET', 'POST'])
@login_required
def create_organization():
    """Créer une organisation"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        is_public = request.form.get('is_public') == 'on'
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute('''
                INSERT INTO organizations (name, description, owner_id, is_public)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            ''', (name, description, request.user_id, is_public))
            
            org_id = cur.fetchone()['id']
            
            # Ajouter le créateur comme admin
            cur.execute('''
                INSERT INTO organization_members (organization_id, user_id, role)
                VALUES (%s, %s, 'admin')
            ''', (org_id, request.user_id))
            
            conn.commit()
            
            flash('Organisation créée avec succès!', 'success')
            return redirect(url_for('organization_view', org_id=org_id))
            
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('Une organisation avec ce nom existe déjà', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'Erreur: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('create_organization.html')

# ============================================================================
# INITIALISATION
# ============================================================================

@app.before_first_request
def initialize_app():
    """Initialise l'application au premier démarrage"""
    # Initialiser PostgreSQL
    try:
        init_postgresql()
        print("✅ PostgreSQL initialized")
    except Exception as e:
        print(f"❌ PostgreSQL initialization failed: {e}")
    
    # Créer l'admin par défaut si non existant
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cur.fetchone()[0]
        
        if admin_count == 0:
            salt, hashed = hash_password_secure('admin123')
            cur.execute(
                "INSERT INTO users (username, email, password, salt, role, is_verified) VALUES (%s, %s, %s, %s, %s, %s)",
                ('admin', 'admin@zenvhub.com', hashed, salt, 'admin', True)
            )
            conn.commit()
            print("✅ Default admin user created: admin / admin123")
    except Exception as e:
        print(f"❌ Admin creation failed: {e}")
    finally:
        cur.close()
        conn.close()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Lancer l'initialisation
    initialize_app()
    
    # Démarrer le serveur
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    )
