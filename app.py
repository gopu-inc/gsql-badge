"""
Zenv Package Hub - Version complète avec synchronisation Git en temps réel
"""

import os
import json
import re
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
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, redirect, url_for, send_file, Response, g
from flask_cors import CORS
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
import yaml
from packaging.version import parse as parse_version

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'zenv_hub.db')
GIT_REPO_PATH = os.path.join(BASE_DIR, 'zenv-data')
GIT_AUTO_COMMIT = True  # Sauvegarde automatique dans Git

# Configuration GitHub
GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "package-data"

# Configuration JWT
JWT_SECRET = "votre_super_secret_jwt_changez_moi_12345"
APP_SECRET = "votre_app_secret_changez_moi_67890"

# Initialisation Flask
app = Flask(__name__)
CORS(app)

app.config.update(
    SECRET_KEY=APP_SECRET,
    JWT_SECRET_KEY=JWT_SECRET,
    DATABASE_PATH=DATABASE_PATH,
    GIT_REPO_PATH=GIT_REPO_PATH,
    PACKAGE_DIR=os.path.join(BASE_DIR, 'packages'),
    UPLOAD_DIR=os.path.join(BASE_DIR, 'uploads'),
    BUILD_DIR=os.path.join(BASE_DIR, 'builds'),
    BADGES_DIR=os.path.join(BASE_DIR, 'badges'),
    SVG_DIR=os.path.join(BASE_DIR, 'static', 'badges'),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    JWT_ACCESS_TOKEN_EXPIRES=3600,
    JWT_REFRESH_TOKEN_EXPIRES=2592000,
    BCRYPT_ROUNDS=12
)

# Créer les répertoires
for dir_path in [app.config['PACKAGE_DIR'], app.config['UPLOAD_DIR'], 
                 app.config['BUILD_DIR'], app.config['BADGES_DIR'],
                 app.config['SVG_DIR'], 'static']:
    os.makedirs(dir_path, exist_ok=True)

# ============================================================================
# GESTIONNAIRE GIT (Sauvegarde temps réel)
# ============================================================================

class GitSyncManager:
    """Gestionnaire de synchronisation Git en temps réel"""
    
    @staticmethod
    def init_git_repo():
        """Initialiser le dépôt Git"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            print(f"🔄 Initialisation du dépôt Git...")
            os.makedirs(repo_path, exist_ok=True)
            
            try:
                # Initialiser Git
                subprocess.run(['git', 'init'], cwd=repo_path, check=True, capture_output=True)
                
                # Configurer Git
                subprocess.run(['git', 'config', 'user.name', GITHUB_USERNAME], 
                             cwd=repo_path, check=True)
                subprocess.run(['git', 'config', 'user.email', GITHUB_EMAIL], 
                             cwd=repo_path, check=True)
                
                # Créer README
                readme_content = f"""# Zenv Package Hub - Backup Repository

Ce dépôt contient les sauvegardes automatiques de Zenv Package Hub.

## Structure
- `zenv_hub.db` : Base de données SQLite complète
- `packages/` : Fichiers de packages (.whl, .tar.gz)
- `badges/` : Fichiers de badges SVG
- `logs/` : Journaux d'activité

## Dernière sauvegarde : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                with open(os.path.join(repo_path, 'README.md'), 'w') as f:
                    f.write(readme_content)
                
                print("✅ Dépôt Git initialisé")
                
            except Exception as e:
                print(f"⚠️ Erreur initialisation Git: {e}")
    
    @staticmethod
    def sync_to_git(action="auto"):
        """Synchroniser toutes les données vers Git"""
        if not GIT_AUTO_COMMIT:
            return True
        
        try:
            repo_path = app.config['GIT_REPO_PATH']
            
            # 1. Copier la base de données
            if os.path.exists(app.config['DATABASE_PATH']):
                shutil.copy2(app.config['DATABASE_PATH'], 
                           os.path.join(repo_path, 'zenv_hub.db'))
            
            # 2. Copier les packages
            packages_src = app.config['PACKAGE_DIR']
            packages_dst = os.path.join(repo_path, 'packages')
            
            if os.path.exists(packages_src):
                if os.path.exists(packages_dst):
                    shutil.rmtree(packages_dst)
                shutil.copytree(packages_src, packages_dst)
            
            # 3. Copier les badges
            badges_src = app.config['SVG_DIR']
            badges_dst = os.path.join(repo_path, 'badges')
            
            if os.path.exists(badges_src):
                if os.path.exists(badges_dst):
                    shutil.rmtree(badges_dst)
                shutil.copytree(badges_src, badges_dst)
            
            # 4. Ajouter tout au Git
            subprocess.run(['git', 'add', '-A'], cwd=repo_path, check=True, capture_output=True)
            
            # 5. Commit avec message descriptif
            commit_msg = f"[{action}] Backup automatique - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            result = subprocess.run(['git', 'commit', '-m', commit_msg], 
                                  cwd=repo_path, capture_output=True, text=True)
            
            # Si rien à committer
            if "nothing to commit" in result.stdout:
                print("ℹ️ Rien à synchroniser avec Git")
                return True
            
            print(f"✅ Données synchronisées avec Git: {commit_msg}")
            
            # 6. Push vers GitHub (si configuré)
            if GITHUB_TOKEN and GITHUB_REPO != "gopu-inc/zenv":
                try:
                    # Configurer l'URL avec token
                    remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
                    
                    # Vérifier si remote existe
                    remote_check = subprocess.run(['git', 'remote', '-v'], 
                                                cwd=repo_path, capture_output=True, text=True)
                    
                    if "origin" not in remote_check.stdout:
                        subprocess.run(['git', 'remote', 'add', 'origin', remote_url], 
                                     cwd=repo_path, check=True)
                    else:
                        subprocess.run(['git', 'remote', 'set-url', 'origin', remote_url], 
                                     cwd=repo_path, check=True)
                    
                    # Push avec force si nécessaire
                    subprocess.run(['git', 'push', '-u', 'origin', 'main', '--force'], 
                                 cwd=repo_path, check=True, capture_output=True)
                    
                    print("✅ Données poussées vers GitHub")
                    
                except Exception as e:
                    print(f"⚠️ Erreur push GitHub: {e}")
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur synchronisation Git: {e}")
            return False
    
    @staticmethod
    def restore_from_git():
        """Restaurer les données depuis Git"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            return False
        
        try:
            # Pull les dernières modifications (si remote configuré)
            if GITHUB_TOKEN:
                try:
                    subprocess.run(['git', 'pull', 'origin', 'main'], 
                                 cwd=repo_path, check=True, capture_output=True)
                except:
                    pass
            
            # 1. Restaurer la base de données
            db_backup = os.path.join(repo_path, 'zenv_hub.db')
            if os.path.exists(db_backup):
                shutil.copy2(db_backup, app.config['DATABASE_PATH'])
                print("✅ Base de données restaurée depuis Git")
            
            # 2. Restaurer les packages
            packages_backup = os.path.join(repo_path, 'packages')
            if os.path.exists(packages_backup):
                if os.path.exists(app.config['PACKAGE_DIR']):
                    shutil.rmtree(app.config['PACKAGE_DIR'])
                shutil.copytree(packages_backup, app.config['PACKAGE_DIR'])
                print("✅ Packages restaurés depuis Git")
            
            # 3. Restaurer les badges
            badges_backup = os.path.join(repo_path, 'badges')
            if os.path.exists(badges_backup):
                if os.path.exists(app.config['SVG_DIR']):
                    shutil.rmtree(app.config['SVG_DIR'])
                shutil.copytree(badges_backup, app.config['SVG_DIR'])
                print("✅ Badges restaurés depuis Git")
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur restauration Git: {e}")
            return False

# ============================================================================
# UTILITAIRES SQLITE
# ============================================================================

def get_db():
    """Obtenir la connexion SQLite"""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE_PATH'])
        g.db.row_factory = sqlite3.Row
    
    return g.db

def close_db(e=None):
    """Fermer la connexion SQLite"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_sqlite():
    """Initialiser la base de données SQLite"""
    print("🔄 Initialisation SQLite...")
    
    try:
        db = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = db.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usrs'")
        if cursor.fetchone() is None:
            print("🔄 Création des tables SQLite...")
            
            # Table usrs
            cursor.execute('''
                CREATE TABLE usrs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_verified BOOLEAN DEFAULT 1,
                    last_login TIMESTAMP,
                    avatar_url TEXT,
                    bio TEXT
                )
            ''')
            
            # Table packages
            cursor.execute('''
                CREATE TABLE packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    version TEXT NOT NULL,
                    author TEXT,
                    author_email TEXT,
                    license TEXT,
                    python_requires TEXT,
                    dependencies TEXT,
                    readme TEXT,
                    github_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    usr_id INTEGER,
                    downloads_count INTEGER DEFAULT 0,
                    is_private BOOLEAN DEFAULT 0,
                    language TEXT DEFAULT 'python',
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE CASCADE
                )
            ''')
            
            # Table badges
            cursor.execute('''
                CREATE TABLE badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    value TEXT NOT NULL,
                    color TEXT DEFAULT 'blue',
                    svg_content TEXT NOT NULL,
                    base64_content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    usage_count INTEGER DEFAULT 0,
                    FOREIGN KEY (created_by) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table logos
            cursor.execute('''
                CREATE TABLE logos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    base64_content TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by INTEGER,
                    is_default BOOLEAN DEFAULT 0,
                    FOREIGN KEY (created_by) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table releases (fichiers)
            cursor.execute('''
                CREATE TABLE releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id INTEGER,
                    version TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER,
                    file_hash TEXT,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    download_count INTEGER DEFAULT 0,
                    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
                )
            ''')
            
            # Table downloads
            cursor.execute('''
                CREATE TABLE downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_id INTEGER,
                    usr_id INTEGER,
                    download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE,
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table sync_log (pour tracking Git)
            cursor.execute('''
                CREATE TABLE sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id INTEGER,
                    sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'success',
                    error_message TEXT
                )
            ''')
            
            db.commit()
            print("✅ Tables SQLite créées avec succès")
            
            # Créer l'admin par défaut
            hashed_pw = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
            cursor.execute('''
                INSERT OR IGNORE INTO usrs (username, email, password, role, is_verified)
                VALUES (?, ?, ?, ?, ?)
            ''', ('admin', 'admin@zenvhub.com', hashed_pw, 'admin', 1))
            
            db.commit()
            print("✅ Admin créé: admin / admin123")
        else:
            print("✅ Tables SQLite existent déjà")
            
        cursor.close()
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Erreur initialisation SQLite: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# UTILITAIRES
# ============================================================================

class SecurityUtils:
    """Utilitaires de sécurité"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except:
            return False
    
    @staticmethod
    def generate_token(usr_id: int, role: str = "user") -> dict:
        access_payload = {
            'usr_id': usr_id,
            'role': role,
            'type': 'access',
            'exp': datetime.utcnow() + timedelta(seconds=app.config['JWT_ACCESS_TOKEN_EXPIRES']),
            'iat': datetime.utcnow(),
            'jti': str(uuid.uuid4())
        }
        
        access_token = jwt.encode(access_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        return {
            'access_token': access_token,
            'expires_in': app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
    
    @staticmethod
    def verify_token(token: str):
        try:
            return jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise Exception("Token expiré")
        except jwt.InvalidTokenError:
            raise Exception("Token invalide")

class BadgeGenerator:
    """Générateur de badges"""
    
    COLORS = {
        'blue': '#007ec6',
        'green': '#4c1',
        'red': '#e05d44',
        'orange': '#fe7d37',
        'yellow': '#dfb317',
        'purple': '#9f5f9f',
        'gray': '#9f9f9f'
    }
    
    @staticmethod
    def create_svg_badge(label: str, value: str, color: str = "blue") -> str:
        color_hex = BadgeGenerator.COLORS.get(color, BadgeGenerator.COLORS['blue'])
        
        label_width = max(len(label) * 6 + 10, 30)
        value_width = max(len(value) * 6 + 10, 30)
        total_width = label_width + value_width
        height = 20
        
        svg = f'<?xml version="1.0" encoding="UTF-8"?>'
        svg += f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{height}" role="img" aria-label="{label}: {value}">'
        svg += f'<title>{label}: {value}</title>'
        svg += f'<linearGradient id="s" x2="0" y2="100%">'
        svg += f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        svg += f'<stop offset="1" stop-opacity=".1"/>'
        svg += f'</linearGradient>'
        svg += f'<mask id="r">'
        svg += f'<rect width="{total_width}" height="{height}" rx="3" fill="#fff"/>'
        svg += f'</mask>'
        svg += f'<g mask="url(#r)">'
        svg += f'<rect width="{label_width}" height="{height}" fill="{color_hex}"/>'
        svg += f'<rect x="{label_width}" width="{value_width}" height="{height}" fill="#555"/>'
        svg += f'<rect width="{total_width}" height="{height}" fill="url(#s)"/>'
        svg += f'</g>'
        svg += f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        svg += f'<text x="{label_width/2}" y="14" fill="#010101" fill-opacity=".3">{label.upper()}</text>'
        svg += f'<text x="{label_width/2}" y="13">{label.upper()}</text>'
        svg += f'<text x="{label_width + value_width/2}" y="14" fill="#010101" fill-opacity=".3">{value}</text>'
        svg += f'<text x="{label_width + value_width/2}" y="13">{value}</text>'
        svg += f'</g>'
        svg += f'</svg>'
        
        return svg
    
    @staticmethod
    def svg_to_base64(svg_content: str) -> str:
        svg_bytes = svg_content.encode('utf-8')
        base64_str = base64.b64encode(svg_bytes).decode('utf-8')
        return f"data:image/svg+xml;base64,{base64_str}"

# ============================================================================
# DÉCORATEURS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if " " in auth_header:
                token = auth_header.split(" ")[1]
            else:
                token = auth_header
        
        if not token:
            return jsonify({'error': 'Token manquant'}), 401
        
        try:
            data = SecurityUtils.verify_token(token)
            g.usr_id = data['usr_id']
            g.role = data['role']
        except Exception as e:
            return jsonify({'error': str(e)}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    @token_required
    def decorated_function(*args, **kwargs):
        if g.role != 'admin':
            return jsonify({'error': 'Accès refusé'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# ROUTES API - AUTHENTIFICATION
# ============================================================================

@app.route('/')
def index():
    return jsonify({
        'message': 'Zenv Package Hub API',
        'version': '2.0.0',
        'features': ['Git Sync', 'Package Hosting', 'Badge Generator', 'JWT Auth'],
        'endpoints': {
            'auth': '/api/auth/*',
            'packages': '/api/packages/*',
            'badges': '/api/badges/*',
            'logos': '/api/logos/*',
            'sync': '/api/sync/*'
        }
    })

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or 'username' not in data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    username = data['username']
    email = data['email']
    password = data['password']
    
    if len(password) < 8:
        return jsonify({'error': 'Mot de passe trop court (min 8 caractères)'}), 400
    
    hashed_pw = SecurityUtils.hash_password(password)
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO usrs (username, email, password)
            VALUES (?, ?, ?)
        ''', (username, email, hashed_pw))
        
        usr_id = cursor.lastrowid
        db.commit()
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git("register")
        
        token = SecurityUtils.generate_token(usr_id, 'user')
        
        return jsonify({
            'message': 'Inscription réussie',
            'user': {'id': usr_id, 'username': username, 'email': email},
            'token': token
        }), 201
        
    except sqlite3.IntegrityError as e:
        if 'username' in str(e):
            return jsonify({'error': 'Nom d\'utilisateur déjà utilisé'}), 400
        elif 'email' in str(e):
            return jsonify({'error': 'Email déjà utilisé'}), 400
        return jsonify({'error': 'Erreur d\'intégrité'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    username = data['username']
    password = data['password']
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT id, username, email, password, role FROM usrs WHERE username = ? OR email = ?', 
                      (username, username))
        row = cursor.fetchone()
        
        if row and SecurityUtils.verify_password(password, row['password']):
            # Mettre à jour last_login
            cursor.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (row['id'],))
            db.commit()
            
            token = SecurityUtils.generate_token(row['id'], row['role'])
            
            # Sauvegarde Git
            GitSyncManager.sync_to_git("login")
            
            return jsonify({
                'message': 'Connexion réussie',
                'user': {
                    'id': row['id'],
                    'username': row['username'],
                    'email': row['email'],
                    'role': row['role']
                },
                'token': token
            })
        else:
            return jsonify({'error': 'Identifiants incorrects'}), 401
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/profile', methods=['GET'])
@token_required
def get_profile():
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT id, username, email, role, created_at, last_login FROM usrs WHERE id = ?', (g.usr_id,))
        row = cursor.fetchone()
        
        if row:
            return jsonify({'user': dict(row)})
        else:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES API - PACKAGES (avec Git Sync)
# ============================================================================

@app.route('/api/packages', methods=['POST'])
@token_required
def create_package():
    """Créer un package (métadonnées)"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'version' not in data:
        return jsonify({'error': 'Nom et version requis'}), 400
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Vérifier si le package existe déjà
        cursor.execute('SELECT id FROM packages WHERE name = ? AND version = ?', 
                      (data['name'], data['version']))
        if cursor.fetchone():
            return jsonify({'error': 'Cette version du package existe déjà'}), 400
        
        cursor.execute('''
            INSERT INTO packages (
                name, description, version, author, author_email,
                license, python_requires, dependencies, readme,
                github_url, usr_id, language
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description', ''),
            data['version'],
            data.get('author', ''),
            data.get('author_email', ''),
            data.get('license', 'MIT'),
            data.get('python_requires', '>=3.6'),
            json.dumps(data.get('dependencies', [])),
            data.get('readme', ''),
            data.get('github_url', ''),
            g.usr_id,
            data.get('language', 'python')
        ))
        
        package_id = cursor.lastrowid
        db.commit()
        
        # Sauvegarde Git immédiate
        GitSyncManager.sync_to_git(f"create_package:{data['name']}")
        
        return jsonify({
            'message': 'Package créé',
            'package': {
                'id': package_id,
                'name': data['name'],
                'version': data['version']
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/upload', methods=['POST'])
@token_required
def upload_package_file():
    """Uploader un fichier de package"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Aucun fichier'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Fichier vide'}), 400
        
        package_name = request.form.get('name')
        version = request.form.get('version')
        
        if not package_name or not version:
            return jsonify({'error': 'Nom et version requis'}), 400
        
        # Vérifier que le package existe
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT id FROM packages WHERE name = ?', (package_name,))
        package_row = cursor.fetchone()
        
        if not package_row:
            # Créer le package automatiquement
            cursor.execute('''
                INSERT INTO packages (name, version, usr_id)
                VALUES (?, ?, ?)
            ''', (package_name, version, g.usr_id))
            package_id = cursor.lastrowid
        else:
            package_id = package_row['id']
        
        # Créer le répertoire
        package_dir = os.path.join(app.config['PACKAGE_DIR'], package_name)
        os.makedirs(package_dir, exist_ok=True)
        
        # Nom du fichier
        file_ext = os.path.splitext(file.filename)[1]
        filename = f"{package_name}-{version}{file_ext}"
        filepath = os.path.join(package_dir, filename)
        
        # Sauvegarder le fichier
        file.save(filepath)
        
        # Calculer le hash
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        # Enregistrer dans releases
        cursor.execute('''
            INSERT OR REPLACE INTO releases 
            (package_id, version, filename, file_path, file_size, file_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (package_id, version, filename, filepath, os.path.getsize(filepath), file_hash))
        
        db.commit()
        
        # Sauvegarde Git immédiate
        GitSyncManager.sync_to_git(f"upload_file:{filename}")
        
        return jsonify({
            'message': 'Fichier uploadé',
            'package': {
                'name': package_name,
                'version': version,
                'filename': filename,
                'size': os.path.getsize(filepath),
                'hash': file_hash,
                'download_url': f'https://zenv-hub.onrender.com/api/packages/download/{package_name}/{version}'
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/download/<package_name>/<version>', methods=['GET'])
def download_package(package_name, version):
    """Télécharger un package"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Chercher le fichier
        cursor.execute('''
            SELECT r.filename, r.file_path 
            FROM releases r
            JOIN packages p ON r.package_id = p.id
            WHERE p.name = ? AND r.version = ?
        ''', (package_name, version))
        
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Package non trouvé'}), 404
        
        filepath = row['file_path']
        filename = row['filename']
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        # Mettre à jour les stats
        cursor.execute('UPDATE packages SET downloads_count = downloads_count + 1 WHERE name = ?', 
                      (package_name,))
        cursor.execute('UPDATE releases SET download_count = download_count + 1 WHERE filename = ?', 
                      (filename,))
        db.commit()
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git(f"download:{filename}")
        
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages', methods=['GET'])
def list_packages():
    """Lister tous les packages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
            ORDER BY p.created_at DESC
        ''')
        
        packages = [dict(row) for row in cursor.fetchall()]
        
        # Ajouter les fichiers disponibles
        for package in packages:
            cursor.execute('SELECT version, filename FROM releases WHERE package_id = ?', 
                          (package['id'],))
            package['files'] = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'packages': packages,
            'count': len(packages)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/<name>', methods=['GET'])
def get_package(name):
    """Obtenir un package spécifique"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.name = ?
        ''', (name,))
        
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Package non trouvé'}), 404
        
        package = dict(row)
        
        # Fichiers disponibles
        cursor.execute('SELECT * FROM releases WHERE package_id = ?', (package['id'],))
        package['releases'] = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({'package': package})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES API - BADGES (avec Git Sync)
# ============================================================================

@app.route('/api/badges', methods=['POST'])
@token_required
def create_badge():
    """Créer un badge"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'label' not in data or 'value' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    name = data['name']
    label = data['label']
    value = data['value']
    color = data.get('color', 'blue')
    
    try:
        # Générer le badge
        svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        base64_content = BadgeGenerator.svg_to_base64(svg_content)
        
        # Sauvegarder le fichier SVG
        badge_path = os.path.join(app.config['SVG_DIR'], f"{name}.svg")
        with open(badge_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        
        # Sauvegarder en base
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO badges (name, label, value, color, svg_content, base64_content, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE 
            SET label = excluded.label,
                value = excluded.value,
                color = excluded.color,
                svg_content = excluded.svg_content,
                base64_content = excluded.base64_content,
                updated_at = CURRENT_TIMESTAMP
        ''', (name, label, value, color, svg_content, base64_content, g.usr_id))
        
        badge_id = cursor.lastrowid
        cursor.execute('UPDATE badges SET usage_count = usage_count + 1 WHERE id = ?', (badge_id,))
        db.commit()
        
        # Sauvegarde Git immédiate
        GitSyncManager.sync_to_git(f"create_badge:{name}")
        
        return jsonify({
            'message': 'Badge créé',
            'badge': {
                'id': badge_id,
                'name': name,
                'label': label,
                'value': value,
                'color': color,
                'svg_url': f'https://zenv-hub.onrender.com/badge/svg/{name}',
                'base64_url': f'https://zenv-hub.onrender.com/badge/base64/{name}',
                'markdown': f'![{label}: {value}](https://zenv-hub.onrender.com/badge/svg/{name})'
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/badges', methods=['GET'])
def list_badges():
    """Lister tous les badges"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.is_active = 1
            ORDER BY b.usage_count DESC
        ''')
        
        badges = []
        for row in cursor.fetchall():
            badge = dict(row)
            badge['svg_url'] = f'https://zenv-hub.onrender.com/badge/svg/{badge["name"]}'
            badge['base64_url'] = f'https://zenv-hub.onrender.com/badge/base64/{badge["name"]}'
            badges.append(badge)
        
        return jsonify({
            'badges': badges,
            'count': len(badges)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/badge/svg/<name>', methods=['GET'])
def serve_badge_svg(name):
    """Servir un badge SVG"""
    badge_path = os.path.join(app.config['SVG_DIR'], f"{name}.svg")
    
    if os.path.exists(badge_path):
        return send_file(badge_path, mimetype='image/svg+xml')
    
    # Générer à la volée depuis la base
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT svg_content FROM badges WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if row and row['svg_content']:
            return Response(row['svg_content'], mimetype='image/svg+xml')
    except:
        pass
    
    # Badge par défaut
    svg_content = BadgeGenerator.create_svg_badge("404", "Not Found", "red")
    return Response(svg_content, mimetype='image/svg+xml')

@app.route('/badge/base64/<name>', methods=['GET'])
def serve_badge_base64(name):
    """Servir un badge en Base64"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT base64_content FROM badges WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if row and row['base64_content']:
            base64_data = row['base64_content']
            if ',' in base64_data:
                image_data = base64.b64decode(base64_data.split(',')[1])
                mime_type = base64_data.split(',')[0].split(':')[1].split(';')[0]
            else:
                image_data = base64.b64decode(base64_data)
                mime_type = 'image/svg+xml'
            
            return Response(image_data, mimetype=mime_type)
    except:
        pass
    
    # Badge par défaut
    svg_content = BadgeGenerator.create_svg_badge("404", "Not Found", "red")
    return Response(svg_content, mimetype='image/svg+xml')

@app.route('/badge/custom/<label>/<value>', methods=['GET'])
@app.route('/badge/custom/<label>/<value>/<color>', methods=['GET'])
def generate_custom_badge(label, value, color="blue"):
    """Générer un badge personnalisé à la volée"""
    svg_content = BadgeGenerator.create_svg_badge(label, value, color)
    return Response(svg_content, mimetype='image/svg+xml')

# ============================================================================
# ROUTES API - LOGOS
# ============================================================================

@app.route('/api/logos', methods=['POST'])
@token_required
def create_logo():
    """Créer un logo en Base64"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'base64_content' not in data or 'mime_type' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        if data.get('is_default', False):
            cursor.execute('UPDATE logos SET is_default = 0 WHERE is_default = 1')
        
        cursor.execute('''
            INSERT INTO logos (name, base64_content, mime_type, created_by, is_default)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE 
            SET base64_content = excluded.base64_content,
                mime_type = excluded.mime_type,
                updated_at = CURRENT_TIMESTAMP,
                is_default = excluded.is_default
        ''', (data['name'], data['base64_content'], data['mime_type'], g.usr_id, data.get('is_default', False)))
        
        logo_id = cursor.lastrowid
        db.commit()
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git(f"create_logo:{data['name']}")
        
        return jsonify({
            'message': 'Logo créé',
            'logo': {
                'id': logo_id,
                'name': data['name'],
                'mime_type': data['mime_type'],
                'is_default': data.get('is_default', False)
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logo/<name>', methods=['GET'])
def serve_logo(name):
    """Servir un logo"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT base64_content, mime_type FROM logos WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if row:
            base64_data = row['base64_content']
            if ',' in base64_data:
                image_data = base64.b64decode(base64_data.split(',')[1])
                mime_type = row['mime_type']
            else:
                image_data = base64.b64decode(base64_data)
                mime_type = 'image/svg+xml'
            
            return Response(image_data, mimetype=mime_type)
    except:
        pass
    
    # Logo par défaut
    svg_content = BadgeGenerator.create_svg_badge("LOGO", "404", "red")
    return Response(svg_content, mimetype='image/svg+xml')

# ============================================================================
# ROUTES API - SYNCHRONISATION
# ============================================================================

@app.route('/api/sync/now', methods=['POST'])
@admin_required
def sync_now():
    """Forcer une synchronisation Git immédiate"""
    try:
        success = GitSyncManager.sync_to_git("manual_sync")
        
        if success:
            return jsonify({
                'message': 'Synchronisation Git réussie',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({'error': 'Échec de synchronisation'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync/status', methods=['GET'])
@admin_required
def sync_status():
    """Obtenir le statut de synchronisation"""
    repo_path = app.config['GIT_REPO_PATH']
    
    status = {
        'git_enabled': GIT_AUTO_COMMIT,
        'repo_exists': os.path.exists(repo_path),
        'last_sync': None,
        'commit_count': 0
    }
    
    if os.path.exists(repo_path):
        try:
            # Dernier commit
            result = subprocess.run(['git', 'log', '-1', '--format=%H|%s|%cd'], 
                                  cwd=repo_path, capture_output=True, text=True)
            if result.stdout:
                commit_hash, commit_msg, commit_date = result.stdout.strip().split('|')
                status['last_commit'] = {
                    'hash': commit_hash[:8],
                    'message': commit_msg,
                    'date': commit_date
                }
            
            # Nombre de commits
            result = subprocess.run(['git', 'rev-list', '--count', 'HEAD'], 
                                  cwd=repo_path, capture_output=True, text=True)
            if result.stdout:
                status['commit_count'] = int(result.stdout.strip())
                
        except Exception as e:
            status['git_error'] = str(e)
    
    return jsonify(status)

# ============================================================================
# INITIALISATION
# ============================================================================

def initialize_app():
    """Initialiser l'application"""
    print("🚀 Initialisation de Zenv Package Hub...")
    
    # Initialiser SQLite
    success = init_sqlite()
    if success:
        print("✅ SQLite initialisé")
    else:
        print("⚠️ SQLite déjà initialisé")
    
    # Initialiser Git
    GitSyncManager.init_git_repo()
    
    # Restaurer depuis Git
    GitSyncManager.restore_from_git()
    
    print("🎉 Application prête avec synchronisation Git!")

# ============================================================================
# HOOKS FLASK
# ============================================================================

@app.teardown_appcontext
def teardown_db(exception):
    """Fermer la base de données"""
    close_db()

@app.after_request
def after_request(response):
    """Synchroniser avec Git après certaines actions"""
    if response.status_code in [200, 201] and GIT_AUTO_COMMIT:
        try:
            # Ne pas synchroniser pour les requêtes GET ou les downloads
            if request.method in ['POST', 'PUT', 'DELETE']:
                if not request.path.startswith('/badge/') and not request.path.startswith('/logo/'):
                    GitSyncManager.sync_to_git(f"after_{request.method}")
        except:
            pass
    return response

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

# Initialiser l'application au démarrage
initialize_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'True') == 'True'
    )
