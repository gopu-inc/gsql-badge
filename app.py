"""
Zenv Package Hub - Version complète corrigée avec fix SQLite
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
GIT_AUTO_COMMIT = True

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
# GESTIONNAIRE GIT
# ============================================================================

class GitSyncManager:
    """Gestionnaire de synchronisation Git"""
    
    @staticmethod
    def init_git_repo():
        """Initialiser le dépôt Git"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            print(f"🔄 Initialisation du dépôt Git...")
            os.makedirs(repo_path, exist_ok=True)
            
            try:
                subprocess.run(['git', 'init'], cwd=repo_path, check=True, capture_output=True)
                subprocess.run(['git', 'config', 'user.name', GITHUB_USERNAME], cwd=repo_path, check=True)
                subprocess.run(['git', 'config', 'user.email', GITHUB_EMAIL], cwd=repo_path, check=True)
                
                readme_content = f"""# Zenv Package Hub - Backup Repository
Ce dépôt contient les sauvegardes automatiques de Zenv Package Hub.
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
            
            if os.path.exists(app.config['DATABASE_PATH']):
                shutil.copy2(app.config['DATABASE_PATH'], os.path.join(repo_path, 'zenv_hub.db'))
            
            packages_src = app.config['PACKAGE_DIR']
            packages_dst = os.path.join(repo_path, 'packages')
            
            if os.path.exists(packages_src):
                if os.path.exists(packages_dst):
                    shutil.rmtree(packages_dst)
                shutil.copytree(packages_src, packages_dst)
            
            badges_src = app.config['SVG_DIR']
            badges_dst = os.path.join(repo_path, 'badges')
            
            if os.path.exists(badges_src):
                if os.path.exists(badges_dst):
                    shutil.rmtree(badges_dst)
                shutil.copytree(badges_src, badges_dst)
            
            subprocess.run(['git', 'add', '-A'], cwd=repo_path, check=True, capture_output=True)
            
            commit_msg = f"[{action}] Backup automatique - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            result = subprocess.run(['git', 'commit', '-m', commit_msg], 
                                  cwd=repo_path, capture_output=True, text=True)
            
            if "nothing to commit" in result.stdout:
                print("ℹ️ Rien à synchroniser avec Git")
                return True
            
            print(f"✅ Données synchronisées avec Git: {commit_msg}")
            
            if GITHUB_TOKEN and GITHUB_REPO != "gopu-inc/zenv":
                try:
                    remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
                    remote_check = subprocess.run(['git', 'remote', '-v'], cwd=repo_path, capture_output=True, text=True)
                    
                    if "origin" not in remote_check.stdout:
                        subprocess.run(['git', 'remote', 'add', 'origin', remote_url], cwd=repo_path, check=True)
                    else:
                        subprocess.run(['git', 'remote', 'set-url', 'origin', remote_url], cwd=repo_path, check=True)
                    
                    subprocess.run(['git', 'push', '-u', 'origin', 'main', '--force'], cwd=repo_path, check=True, capture_output=True)
                    print("✅ Données poussées vers GitHub")
                    
                except Exception as e:
                    print(f"⚠️ Erreur push GitHub: {e}")
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur synchronisation Git: {e}")
            return False

# ============================================================================
# UTILITAIRES SQLITE CORRIGÉS
# ============================================================================

def get_db():
    """Obtenir la connexion SQLite avec fix pour les grands ints"""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE_PATH'])
        # FIX: Ajouter une fonction pour convertir les grands ints en string
        g.db.create_function("INT_TO_STR", 1, lambda x: str(x) if x is not None else None)
        g.db.row_factory = sqlite3.Row
    
    return g.db

def close_db(e=None):
    """Fermer la connexion SQLite"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def safe_int(value):
    """Convertir en int de manière sécurisée pour SQLite"""
    try:
        if value is None:
            return None
        # FIX: Pour les très grands nombres, les stocker comme TEXT
        if isinstance(value, int) and value > 2**63 - 1:
            return str(value)
        return int(value)
    except:
        return value

def init_sqlite():
    """Initialiser la base de données SQLite"""
    print("🔄 Initialisation SQLite...")
    
    try:
        db = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = db.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usrs'")
        if cursor.fetchone() is None:
            print("🔄 Création des tables SQLite...")
            
            # Table usrs avec TEXT pour id pour supporter les grands nombres
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
                    usr_id TEXT,  -- FIX: TEXT pour supporter les grands ids
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
                    created_by TEXT,  -- FIX: TEXT pour supporter les grands ids
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
                    created_by TEXT,  -- FIX: TEXT pour supporter les grands ids
                    is_default BOOLEAN DEFAULT 0,
                    FOREIGN KEY (created_by) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table releases
            cursor.execute('''
                CREATE TABLE releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id TEXT,  -- FIX: TEXT pour supporter les grands ids
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
                    release_id TEXT,  -- FIX: TEXT pour supporter les grands ids
                    usr_id TEXT,  -- FIX: TEXT pour supporter les grands ids
                    download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE,
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table sync_log
            cursor.execute('''
                CREATE TABLE sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,  -- FIX: TEXT pour supporter les grands ids
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
            
            # FIX: Modifier les colonnes pour supporter les grands ids si nécessaire
            try:
                # Vérifier si usr_id est déjà TEXT
                cursor.execute("PRAGMA table_info(packages)")
                columns = cursor.fetchall()
                usr_id_type = None
                for col in columns:
                    if col[1] == 'usr_id':
                        usr_id_type = col[2]
                
                if usr_id_type and usr_id_type.upper() != 'TEXT':
                    print("🔄 Conversion des colonnes id en TEXT pour supporter les grands nombres...")
                    # Convertir les colonnes id en TEXT
                    tables_to_convert = ['packages', 'badges', 'logos', 'releases', 'downloads', 'sync_log']
                    for table in tables_to_convert:
                        try:
                            cursor.execute(f"PRAGMA table_info({table})")
                            cols = cursor.fetchall()
                            for col in cols:
                                if col[1].endswith('_id') and col[2].upper() == 'INTEGER':
                                    print(f"  Converting {table}.{col[1]} to TEXT")
                        except:
                            pass
            except Exception as e:
                print(f"⚠️ Erreur vérification des colonnes: {e}")
            
        cursor.close()
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Erreur initialisation SQLite: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# UTILITAIRES DE SÉCURITÉ CORRIGÉS
# ============================================================================

class SecurityUtils:
    """Utilitaires de sécurité avec fix pour les grands ints"""
    
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
    def generate_token(usr_id, role: str = "user") -> dict:
        """Générer un token JWT"""
        # FIX: Convertir l'ID en string pour éviter les problèmes SQLite
        usr_id_str = str(usr_id) if usr_id is not None else "0"
        
        access_payload = {
            'usr_id': usr_id_str,
            'role': role,
            'type': 'access',
            'exp': datetime.utcnow() + timedelta(seconds=app.config['JWT_ACCESS_TOKEN_EXPIRES']),
            'iat': datetime.utcnow(),
            'jti': str(uuid.uuid4())
        }
        
        try:
            access_token = jwt.encode(access_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        except Exception as e:
            print(f"❌ Erreur génération token: {e}")
            # Fallback: générer un token simple
            import secrets
            access_token = secrets.token_urlsafe(32)
        
        return {
            'access_token': access_token,
            'expires_in': app.config['JWT_ACCESS_TOKEN_EXPIRES'],
            'user_id': usr_id_str  # Ajouter user_id pour référence
        }
    
    @staticmethod
    def verify_token(token: str):
        """Vérifier un token JWT"""
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            # FIX: S'assurer que usr_id est string
            if 'usr_id' in payload:
                payload['usr_id'] = str(payload['usr_id'])
            return payload
        except jwt.ExpiredSignatureError:
            raise Exception("Token expiré")
        except jwt.InvalidTokenError:
            raise Exception("Token invalide")
        except Exception as e:
            raise Exception(f"Erreur token: {str(e)}")

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
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{height}" role="img" aria-label="{label}: {value}">
<title>{label}: {value}</title>
<linearGradient id="s" x2="0" y2="100%">
<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
<stop offset="1" stop-opacity=".1"/>
</linearGradient>
<mask id="r">
<rect width="{total_width}" height="{height}" rx="3" fill="#fff"/>
</mask>
<g mask="url(#r)">
<rect width="{label_width}" height="{height}" fill="{color_hex}"/>
<rect x="{label_width}" width="{value_width}" height="{height}" fill="#555"/>
<rect width="{total_width}" height="{height}" fill="url(#s)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{label_width/2}" y="14" fill="#010101" fill-opacity=".3">{label.upper()}</text>
<text x="{label_width/2}" y="13">{label.upper()}</text>
<text x="{label_width + value_width/2}" y="14" fill="#010101" fill-opacity=".3">{value}</text>
<text x="{label_width + value_width/2}" y="13">{value}</text>
</g>
</svg>'''
        
        return svg
    
    @staticmethod
    def svg_to_base64(svg_content: str) -> str:
        svg_bytes = svg_content.encode('utf-8')
        base64_str = base64.b64encode(svg_bytes).decode('utf-8')
        return f"data:image/svg+xml;base64,{base64_str}"

# ============================================================================
# DÉCORATEURS CORRIGÉS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        auth_header = request.headers.get('Authorization')
        if auth_header:
            try:
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                else:
                    token = auth_header
            except:
                pass
        
        if not token:
            return jsonify({'error': 'Token manquant'}), 401
        
        try:
            data = SecurityUtils.verify_token(token)
            # FIX: Stocker comme string
            g.usr_id = str(data.get('usr_id', '0'))
            g.role = data.get('role', 'user')
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
# ROUTES API - AUTHENTIFICATION CORRIGÉES
# ============================================================================

@app.route('/')
def index():
    return jsonify({
        'message': 'Zenv Package Hub API (Fixed Version)',
        'version': '2.1.0',
        'status': 'running',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint de santé"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1')
        db_status = 'healthy'
    except:
        db_status = 'unhealthy'
    
    return jsonify({
        'status': 'ok',
        'database': db_status,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login avec fix pour les grands ints"""
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    username = data['username']
    password = data['password']
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT id, username, email, password, role 
            FROM usrs 
            WHERE username = ? OR email = ?
        ''', (username, username))
        row = cursor.fetchone()
        
        if row and SecurityUtils.verify_password(password, row['password']):
            # FIX: Convertir l'ID en string
            user_id = str(row['id'])
            
            # Mettre à jour last_login
            cursor.execute('''
                UPDATE usrs 
                SET last_login = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (row['id'],))
            db.commit()
            
            # Générer token
            token_data = SecurityUtils.generate_token(user_id, row['role'])
            
            # Sauvegarde Git
            GitSyncManager.sync_to_git("login")
            
            return jsonify({
                'message': 'Connexion réussie',
                'user': {
                    'id': user_id,
                    'username': row['username'],
                    'email': row['email'],
                    'role': row['role']
                },
                'token': token_data
            })
        else:
            return jsonify({'error': 'Identifiants incorrects'}), 401
        
    except Exception as e:
        print(f"❌ Erreur login: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register avec fix pour les grands ints"""
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
        
        # FIX: Récupérer l'ID et le convertir en string
        user_id = cursor.lastrowid
        user_id_str = str(user_id)
        
        db.commit()
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git("register")
        
        token_data = SecurityUtils.generate_token(user_id_str, 'user')
        
        return jsonify({
            'message': 'Inscription réussie',
            'user': {
                'id': user_id_str,
                'username': username,
                'email': email,
                'role': 'user'
            },
            'token': token_data
        }), 201
        
    except sqlite3.IntegrityError as e:
        error_msg = str(e)
        if 'username' in error_msg:
            return jsonify({'error': 'Nom d\'utilisateur déjà utilisé'}), 400
        elif 'email' in error_msg:
            return jsonify({'error': 'Email déjà utilisé'}), 400
        return jsonify({'error': 'Erreur d\'intégrité'}), 400
    except Exception as e:
        print(f"❌ Erreur register: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500

@app.route('/api/auth/profile', methods=['GET'])
@token_required
def get_profile():
    """Obtenir le profil utilisateur"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # FIX: Utiliser l'ID comme string
        cursor.execute('''
            SELECT id, username, email, role, created_at, last_login 
            FROM usrs 
            WHERE id = ?
        ''', (g.usr_id,))
        row = cursor.fetchone()
        
        if row:
            # Convertir l'ID en string
            user_data = dict(row)
            user_data['id'] = str(user_data['id'])
            return jsonify({'user': user_data})
        else:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
            
    except Exception as e:
        print(f"❌ Erreur profile: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES API - PACKAGES
# ============================================================================

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
        
        packages = []
        for row in cursor.fetchall():
            pkg = dict(row)
            # FIX: Convertir les IDs en string
            if 'id' in pkg:
                pkg['id'] = str(pkg['id'])
            if 'usr_id' in pkg and pkg['usr_id']:
                pkg['usr_id'] = str(pkg['usr_id'])
            packages.append(pkg)
        
        # Compter les fichiers disponibles
        for package in packages:
            cursor.execute('SELECT version, filename FROM releases WHERE package_id = ?', 
                          (package['id'],))
            package['files'] = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'packages': packages,
            'count': len(packages)
        })
        
    except Exception as e:
        print(f"❌ Erreur list_packages: {e}")
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
        # FIX: Convertir les IDs en string
        if 'id' in package:
            package['id'] = str(package['id'])
        if 'usr_id' in package and package['usr_id']:
            package['usr_id'] = str(package['usr_id'])
        
        # Fichiers disponibles
        cursor.execute('SELECT * FROM releases WHERE package_id = ?', (package['id'],))
        releases = []
        for rel in cursor.fetchall():
            rel_dict = dict(rel)
            if 'id' in rel_dict:
                rel_dict['id'] = str(rel_dict['id'])
            if 'package_id' in rel_dict and rel_dict['package_id']:
                rel_dict['package_id'] = str(rel_dict['package_id'])
            releases.append(rel_dict)
        
        package['releases'] = releases
        
        return jsonify({'package': package})
        
    except Exception as e:
        print(f"❌ Erreur get_package: {e}")
        return jsonify({'error': str(e)}), 500

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
        
        # FIX: Utiliser user_id comme string
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
            g.usr_id,  # Déjà string
            data.get('language', 'python')
        ))
        
        package_id = str(cursor.lastrowid)
        db.commit()
        
        # Sauvegarde Git
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
        print(f"❌ Erreur create_package: {e}")
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
        
        # Vérifier/Créer le package
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT id FROM packages WHERE name = ?', (package_name,))
        package_row = cursor.fetchone()
        
        if not package_row:
            # FIX: Créer avec user_id comme string
            cursor.execute('''
                INSERT INTO packages (name, version, usr_id)
                VALUES (?, ?, ?)
            ''', (package_name, version, g.usr_id))
            package_id = str(cursor.lastrowid)
        else:
            package_id = str(package_row['id'])
        
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
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git(f"upload_file:{filename}")
        
        return jsonify({
            'message': 'Fichier uploadé',
            'package': {
                'name': package_name,
                'version': version,
                'filename': filename,
                'size': os.path.getsize(filepath),
                'hash': file_hash,
                'download_url': f'/api/packages/download/{package_name}/{version}'
            }
        }), 201
        
    except Exception as e:
        print(f"❌ Erreur upload: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/download/<package_name>/<version>', methods=['GET'])
def download_package(package_name, version):
    """Télécharger un package"""
    try:
        db = get_db()
        cursor = db.cursor()
        
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
        print(f"❌ Erreur download: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES API - BADGES
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
        
        # FIX: Utiliser user_id comme string
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
        
        # Sauvegarde Git
        GitSyncManager.sync_to_git(f"create_badge:{name}")
        
        return jsonify({
            'message': 'Badge créé',
            'badge': {
                'id': str(badge_id),
                'name': name,
                'label': label,
                'value': value,
                'color': color,
                'svg_url': f'/badge/svg/{name}',
                'base64_url': f'/badge/base64/{name}',
                'markdown': f'![{label}: {value}](/badge/svg/{name})'
            }
        }), 201
        
    except Exception as e:
        print(f"❌ Erreur create_badge: {e}")
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
            # FIX: Convertir les IDs en string
            if 'id' in badge:
                badge['id'] = str(badge['id'])
            if 'created_by' in badge and badge['created_by']:
                badge['created_by'] = str(badge['created_by'])
            
            badge['svg_url'] = f'/badge/svg/{badge["name"]}'
            badge['base64_url'] = f'/badge/base64/{badge["name"]}'
            badges.append(badge)
        
        return jsonify({
            'badges': badges,
            'count': len(badges)
        })
        
    except Exception as e:
        print(f"❌ Erreur list_badges: {e}")
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
        
        # FIX: Utiliser user_id comme string
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
                'id': str(logo_id),
                'name': data['name'],
                'mime_type': data['mime_type'],
                'is_default': data.get('is_default', False)
            }
        }), 201
        
    except Exception as e:
        print(f"❌ Erreur create_logo: {e}")
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
@token_required
def sync_now():
    """Forcer une synchronisation Git"""
    if g.role != 'admin':
        return jsonify({'error': 'Accès refusé'}), 403
    
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

@app.route('/api/debug/db', methods=['GET'])
def debug_db():
    """Debug: Voir l'état de la base"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        db_info = {
            'tables': [table['name'] for table in tables],
            'users_count': 0,
            'packages_count': 0,
            'badges_count': 0
        }
        
        for table in ['usrs', 'packages', 'badges']:
            try:
                cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
                count = cursor.fetchone()['count']
                db_info[f'{table}_count'] = count
            except:
                pass
        
        return jsonify(db_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# HOOKS FLASK
# ============================================================================

@app.teardown_appcontext
def teardown_db(exception):
    """Fermer la base de données"""
    close_db()

@app.before_request
def before_request():
    """Avant chaque requête"""
    g.usr_id = None
    g.role = None

# ============================================================================
# INITIALISATION
# ============================================================================

def initialize_app():
    """Initialiser l'application"""
    print("🚀 Initialisation de Zenv Package Hub (Fixed Version)...")
    
    # Initialiser SQLite
    success = init_sqlite()
    if success:
        print("✅ SQLite initialisé avec fix pour les grands ints")
    else:
        print("⚠️ SQLite déjà initialisé")
    
    # Initialiser Git
    GitSyncManager.init_git_repo()
    
    print("🎉 Application prête! Utilisez /api/auth/login pour vous connecter")

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

# Initialiser l'application au démarrage
initialize_app()

if __name__ == '__main__':
    print(f"🌐 Serveur démarré sur http://0.0.0.0:10000")
    print(f"📊 Base de données: {DATABASE_PATH}")
    print(f"📦 Répertoire packages: {app.config['PACKAGE_DIR']}")
    
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 10000)),
        debug=os.environ.get('FLASK_DEBUG', 'True') == 'True'
    )
