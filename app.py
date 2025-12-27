"""
Zenv Package Hub - Version SQLite avec synchronisation Git et badges Base64
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

from flask import Flask, request, jsonify, redirect, url_for, session, send_file, Response, g
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

# Configuration GitHub
GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "main"

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
                    github_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_verified BOOLEAN DEFAULT 0,
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
                    UNIQUE(name, version),
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE CASCADE
                )
            ''')
            
            # Table badges avec support Base64
            cursor.execute('''
                CREATE TABLE badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    value TEXT NOT NULL,
                    color TEXT DEFAULT 'blue',
                    svg_content TEXT NOT NULL,
                    base64_content TEXT,
                    base64_type TEXT DEFAULT 'svg',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    usage_count INTEGER DEFAULT 0,
                    FOREIGN KEY (created_by) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table logo
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
            
            # Table badge_assignments
            cursor.execute('''
                CREATE TABLE badge_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    badge_id INTEGER,
                    package_id INTEGER,
                    usr_id INTEGER,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_by INTEGER,
                    UNIQUE(badge_id, package_id, usr_id),
                    FOREIGN KEY (badge_id) REFERENCES badges(id) ON DELETE CASCADE,
                    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE,
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE CASCADE,
                    FOREIGN KEY (assigned_by) REFERENCES usrs(id) ON DELETE SET NULL
                )
            ''')
            
            # Table releases
            cursor.execute('''
                CREATE TABLE releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id INTEGER,
                    version TEXT NOT NULL,
                    filename TEXT,
                    file_size INTEGER,
                    file_hash TEXT,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    download_count INTEGER DEFAULT 0,
                    github_release_id TEXT,
                    UNIQUE(package_id, version),
                    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
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
        """Hash bcrypt"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """Vérifie le mot de passe"""
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except:
            return False
    
    @staticmethod
    def generate_token(usr_id: int, role: str = "user") -> dict:
        """Génère les tokens JWT"""
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
        """Vérifie un token JWT"""
        try:
            return jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise Exception("Token expiré")
        except jwt.InvalidTokenError:
            raise Exception("Token invalide")

class BadgeGenerator:
    """Générateur de badges SVG et Base64"""
    
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
        """Crée un badge SVG"""
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
        """Convertit SVG en Base64"""
        svg_bytes = svg_content.encode('utf-8')
        base64_str = base64.b64encode(svg_bytes).decode('utf-8')
        return f"data:image/svg+xml;base64,{base64_str}"
    
    @staticmethod
    def create_base64_badge(label: str, value: str, color: str = "blue") -> tuple:
        """Crée un badge et retourne SVG + Base64"""
        svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        base64_content = BadgeGenerator.svg_to_base64(svg_content)
        return svg_content, base64_content
    
    @staticmethod
    def create_custom_base64_badge(label: str, value: str, base64_logo: str = None, color: str = "blue") -> tuple:
        """Crée un badge avec logo personnalisé en Base64"""
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
        
        # Ajouter le logo si fourni
        if base64_logo:
            svg += f'<image href="{base64_logo}" x="5" y="2" width="16" height="16"/>'
            label_x = label_width/2 + 8
        else:
            label_x = label_width/2
            
        svg += f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        svg += f'<text x="{label_x}" y="14" fill="#010101" fill-opacity=".3">{label.upper()}</text>'
        svg += f'<text x="{label_x}" y="13">{label.upper()}</text>'
        svg += f'<text x="{label_width + value_width/2}" y="14" fill="#010101" fill-opacity=".3">{value}</text>'
        svg += f'<text x="{label_width + value_width/2}" y="13">{value}</text>'
        svg += f'</g>'
        svg += f'</svg>'
        
        base64_content = BadgeGenerator.svg_to_base64(svg)
        return svg, base64_content
    
    @staticmethod
    def save_badge_svg(badge_name: str, svg_content: str) -> str:
        """Sauvegarde un badge SVG"""
        badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
        with open(badge_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        return badge_path

# ============================================================================
# DÉCORATEURS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1] if " " in request.headers['Authorization'] else request.headers['Authorization']
        
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
# ROUTES API
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil API"""
    return jsonify({
        'message': 'Bienvenue sur Zenv Package Hub API',
        'version': '1.0.0',
        'endpoints': {
            'auth': {
                'register': '/api/auth/register (POST)',
                'login': '/api/auth/login (POST)',
                'profile': '/api/auth/profile (GET)'
            },
            'badges': {
                'list': '/api/badges (GET)',
                'create': '/api/badges (POST)',
                'get': '/api/badges/<name> (GET)',
                'update': '/api/badges/<name> (PUT)',
                'delete': '/api/badges/<name> (DELETE)'
            },
            'logos': {
                'list': '/api/logos (GET)',
                'create': '/api/logos (POST)',
                'get': '/api/logos/<name> (GET)',
                'set_default': '/api/logos/<name>/default (PUT)'
            },
            'packages': {
                'list': '/api/packages (GET)',
                'create': '/api/packages (POST)',
                'get': '/api/packages/<name> (GET)'
            }
        },
        'badge_urls': {
            'svg': 'https://zenv-hub.onrender.com/badge/svg/{badge_name}',
            'base64': 'https://zenv-hub.onrender.com/badge/base64/{badge_name}',
            'custom': 'https://zenv-hub.onrender.com/badge/custom/{label}/{value}/{color}',
            'custom_with_logo': 'https://zenv-hub.onrender.com/badge/custom/{label}/{value}/{color}?logo={logo_name}'
        }
    })

# ============================================================================
# AUTHENTIFICATION
# ============================================================================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Inscription"""
    data = request.get_json()
    
    if not data or 'username' not in data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    username = data['username']
    email = data['email']
    password = data['password']
    
    if len(password) < 8:
        return jsonify({'error': 'Le mot de passe doit contenir au moins 8 caractères'}), 400
    
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
        
        token = SecurityUtils.generate_token(usr_id, 'user')
        
        return jsonify({
            'message': 'Inscription réussie',
            'user': {
                'id': usr_id,
                'username': username,
                'email': email
            },
            'token': token
        }), 201
        
    except sqlite3.IntegrityError as e:
        if 'username' in str(e):
            return jsonify({'error': 'Ce nom d\'utilisateur existe déjà'}), 400
        elif 'email' in str(e):
            return jsonify({'error': 'Cet email est déjà utilisé'}), 400
        else:
            return jsonify({'error': 'Erreur lors de l\'inscription'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Connexion"""
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
            # Mettre à jour last_login
            cursor.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (row['id'],))
            db.commit()
            
            token = SecurityUtils.generate_token(row['id'], row['role'])
            
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
    """Obtenir le profil"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT id, username, email, role, created_at FROM usrs WHERE id = ?', (g.usr_id,))
        row = cursor.fetchone()
        
        if row:
            return jsonify({
                'user': dict(row)
            })
        else:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# LOGOS
# ============================================================================

@app.route('/api/logos', methods=['POST'])
@token_required
def create_logo():
    """Créer un logo en Base64"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'base64_content' not in data or 'mime_type' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    name = data['name']
    base64_content = data['base64_content']
    mime_type = data['mime_type']
    
    # Vérifier que c'est bien du Base64
    try:
        base64.b64decode(base64_content.split(',')[-1] if ',' in base64_content else base64_content)
    except:
        return jsonify({'error': 'Contenu Base64 invalide'}), 400
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Si c'est le logo par défaut, désactiver les autres
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
        ''', (name, base64_content, mime_type, g.usr_id, data.get('is_default', False)))
        
        logo_id = cursor.lastrowid
        db.commit()
        
        return jsonify({
            'message': 'Logo créé avec succès',
            'logo': {
                'id': logo_id,
                'name': name,
                'mime_type': mime_type,
                'is_default': data.get('is_default', False)
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logos', methods=['GET'])
def list_logos():
    """Lister tous les logos"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT id, name, mime_type, created_at, updated_at, created_by, is_default
            FROM logos
            ORDER BY is_default DESC, created_at DESC
        ''')
        
        logos = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'logos': logos,
            'count': len(logos)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logos/<name>', methods=['GET'])
def get_logo(name):
    """Obtenir un logo spécifique"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT name, base64_content, mime_type, is_default
            FROM logos
            WHERE name = ?
        ''', (name,))
        
        row = cursor.fetchone()
        
        if row:
            return jsonify({
                'logo': dict(row)
            })
        else:
            return jsonify({'error': 'Logo non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logos/<name>/default', methods=['PUT'])
@token_required
def set_default_logo(name):
    """Définir un logo comme défaut"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Vérifier si le logo existe
        cursor.execute('SELECT id FROM logos WHERE name = ?', (name,))
        if not cursor.fetchone():
            return jsonify({'error': 'Logo non trouvé'}), 404
        
        # Désactiver tous les logos par défaut
        cursor.execute('UPDATE logos SET is_default = 0 WHERE is_default = 1')
        
        # Définir ce logo comme défaut
        cursor.execute('UPDATE logos SET is_default = 1 WHERE name = ?', (name,))
        db.commit()
        
        return jsonify({'message': f'Logo {name} défini comme défaut'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logo/<name>', methods=['GET'])
def serve_logo(name):
    """Servir un logo en image"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT base64_content, mime_type FROM logos WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if row:
            base64_content = row['base64_content']
            mime_type = row['mime_type']
            
            # Extraire les données Base64
            if ',' in base64_content:
                base64_data = base64_content.split(',')[1]
            else:
                base64_data = base64_content
            
            image_data = base64.b64decode(base64_data)
            return Response(image_data, mimetype=mime_type)
        else:
            # Logo par défaut si non trouvé
            default_svg = BadgeGenerator.create_svg_badge("LOGO", "404", "red")
            return Response(default_svg, mimetype='image/svg+xml')
            
    except Exception as e:
        default_svg = BadgeGenerator.create_svg_badge("ERROR", str(e)[:20], "red")
        return Response(default_svg, mimetype='image/svg+xml')

# ============================================================================
# BADGES
# ============================================================================

@app.route('/api/badges', methods=['POST'])
@token_required
def create_badge():
    """Créer un nouveau badge"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'label' not in data or 'value' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    name = data['name']
    label = data['label']
    value = data['value']
    color = data.get('color', 'blue')
    logo_name = data.get('logo')
    custom_base64 = data.get('base64_content')
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Si un logo est spécifié, le récupérer
        base64_logo = None
        if logo_name:
            cursor.execute('SELECT base64_content FROM logos WHERE name = ?', (logo_name,))
            logo_row = cursor.fetchone()
            if logo_row:
                base64_logo = logo_row['base64_content']
        
        # Si du Base64 personnalisé est fourni, l'utiliser
        if custom_base64:
            svg_content = None
            base64_content = custom_base64
            base64_type = data.get('base64_type', 'custom')
        else:
            # Générer le badge normal ou avec logo
            if base64_logo:
                svg_content, base64_content = BadgeGenerator.create_custom_base64_badge(label, value, base64_logo, color)
            else:
                svg_content, base64_content = BadgeGenerator.create_base64_badge(label, value, color)
            base64_type = 'svg'
        
        # Sauvegarder en base
        cursor.execute('''
            INSERT INTO badges (name, label, value, color, svg_content, base64_content, base64_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE 
            SET label = excluded.label,
                value = excluded.value,
                color = excluded.color,
                svg_content = excluded.svg_content,
                base64_content = excluded.base64_content,
                base64_type = excluded.base64_type,
                updated_at = CURRENT_TIMESTAMP
        ''', (name, label, value, color, svg_content, base64_content, base64_type, g.usr_id))
        
        badge_id = cursor.lastrowid
        
        # Assigner à l'utilisateur
        cursor.execute('''
            INSERT OR IGNORE INTO badge_assignments (badge_id, usr_id, assigned_by)
            VALUES (?, ?, ?)
        ''', (badge_id, g.usr_id, g.usr_id))
        
        # Incrémenter le compteur d'utilisation
        cursor.execute('UPDATE badges SET usage_count = usage_count + 1 WHERE id = ?', (badge_id,))
        
        db.commit()
        
        # Sauvegarder le SVG si généré
        if svg_content:
            BadgeGenerator.save_badge_svg(name, svg_content)
        
        return jsonify({
            'message': 'Badge créé avec succès',
            'badge': {
                'id': badge_id,
                'name': name,
                'label': label,
                'value': value,
                'color': color,
                'base64_url': f'https://zenv-hub.onrender.com/badge/base64/{name}',
                'svg_url': f'https://zenv-hub.onrender.com/badge/svg/{name}',
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
            ORDER BY b.usage_count DESC, b.name
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

@app.route('/api/badges/<name>', methods=['GET'])
def get_badge(name):
    """Obtenir un badge spécifique"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.name = ? AND b.is_active = 1
        ''', (name,))
        
        row = cursor.fetchone()
        
        if row:
            badge = dict(row)
            badge['svg_url'] = f'https://zenv-hub.onrender.com/badge/svg/{badge["name"]}'
            badge['base64_url'] = f'https://zenv-hub.onrender.com/badge/base64/{badge["name"]}'
            badge['markdown'] = f'![{badge["label"]}: {badge["value"]}](https://zenv-hub.onrender.com/badge/svg/{badge["name"]})'
            
            return jsonify({'badge': badge})
        else:
            return jsonify({'error': 'Badge non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/badges/<name>', methods=['PUT'])
@token_required
def update_badge(name):
    """Mettre à jour un badge"""
    data = request.get_json()
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Vérifier si le badge existe et appartient à l'utilisateur
        cursor.execute('SELECT created_by FROM badges WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({'error': 'Badge non trouvé'}), 404
        
        if g.role != 'admin' and row['created_by'] != g.usr_id:
            return jsonify({'error': 'Accès refusé'}), 403
        
        # Mettre à jour les champs
        update_fields = []
        params = []
        
        if 'label' in data:
            update_fields.append('label = ?')
            params.append(data['label'])
        
        if 'value' in data:
            update_fields.append('value = ?')
            params.append(data['value'])
        
        if 'color' in data:
            update_fields.append('color = ?')
            params.append(data['color'])
        
        if update_fields:
            update_fields.append('updated_at = CURRENT_TIMESTAMP')
            params.append(name)
            
            query = f'UPDATE badges SET {", ".join(update_fields)} WHERE name = ?'
            cursor.execute(query, params)
            db.commit()
        
        return jsonify({'message': 'Badge mis à jour'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/badges/<name>', methods=['DELETE'])
@token_required
def delete_badge(name):
    """Supprimer un badge"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Vérifier si le badge existe et appartient à l'utilisateur
        cursor.execute('SELECT created_by FROM badges WHERE name = ?', (name,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({'error': 'Badge non trouvé'}), 404
        
        if g.role != 'admin' and row['created_by'] != g.usr_id:
            return jsonify({'error': 'Accès refusé'}), 403
        
        # Désactiver le badge (soft delete)
        cursor.execute('UPDATE badges SET is_active = 0 WHERE name = ?', (name,))
        db.commit()
        
        return jsonify({'message': 'Badge supprimé'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES BADGES PUBLIC
# ============================================================================

@app.route('/badge/svg/<badge_name>', methods=['GET'])
def serve_badge_svg(badge_name):
    """Servir un badge SVG"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT svg_content FROM badges WHERE name = ? AND is_active = 1', (badge_name,))
        row = cursor.fetchone()
        
        if row and row['svg_content']:
            return Response(row['svg_content'], mimetype='image/svg+xml')
        else:
            # Générer un badge par défaut
            svg_content = BadgeGenerator.create_svg_badge("Not Found", "404", "red")
            return Response(svg_content, mimetype='image/svg+xml')
            
    except Exception as e:
        svg_content = BadgeGenerator.create_svg_badge("Error", str(e)[:20], "red")
        return Response(svg_content, mimetype='image/svg+xml')

@app.route('/badge/base64/<badge_name>', methods=['GET'])
def serve_badge_base64(badge_name):
    """Servir un badge en Base64"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('SELECT base64_content FROM badges WHERE name = ? AND is_active = 1', (badge_name,))
        row = cursor.fetchone()
        
        if row and row['base64_content']:
            # Extraire les données Base64
            base64_content = row['base64_content']
            if ',' in base64_content:
                base64_data = base64_content.split(',')[1]
                mime_type = base64_content.split(',')[0].split(':')[1].split(';')[0]
            else:
                base64_data = base64_content
                mime_type = 'image/svg+xml'
            
            image_data = base64.b64decode(base64_data)
            return Response(image_data, mimetype=mime_type)
        else:
            # Générer un badge par défaut
            svg_content = BadgeGenerator.create_svg_badge("Not Found", "404", "red")
            return Response(svg_content, mimetype='image/svg+xml')
            
    except Exception as e:
        svg_content = BadgeGenerator.create_svg_badge("Error", str(e)[:20], "red")
        return Response(svg_content, mimetype='image/svg+xml')

@app.route('/badge/custom/<label>/<value>', methods=['GET'])
@app.route('/badge/custom/<label>/<value>/<color>', methods=['GET'])
def generate_custom_badge(label, value, color="blue"):
    """Générer un badge personnalisé à la volée"""
    try:
        logo_name = request.args.get('logo')
        base64_logo = None
        
        if logo_name:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('SELECT base64_content FROM logos WHERE name = ?', (logo_name,))
            logo_row = cursor.fetchone()
            if logo_row:
                base64_logo = logo_row['base64_content']
        
        if base64_logo:
            svg_content, _ = BadgeGenerator.create_custom_base64_badge(label, value, base64_logo, color)
        else:
            svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        
        return Response(svg_content, mimetype='image/svg+xml')
        
    except Exception as e:
        svg_content = BadgeGenerator.create_svg_badge("Error", str(e)[:20], "red")
        return Response(svg_content, mimetype='image/svg+xml')

# ============================================================================
# PACKAGES
# ============================================================================

@app.route('/api/packages', methods=['POST'])
@token_required
def create_package():
    """Créer un package"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'version' not in data:
        return jsonify({'error': 'Données manquantes'}), 400
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT INTO packages (
                name, description, version, author, author_email,
                license, python_requires, dependencies, readme,
                github_url, usr_id, language
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description'),
            data['version'],
            data.get('author'),
            data.get('author_email'),
            data.get('license'),
            data.get('python_requires'),
            json.dumps(data.get('dependencies', [])) if data.get('dependencies') else None,
            data.get('readme'),
            data.get('github_url'),
            g.usr_id,
            data.get('language', 'python')
        ))
        
        package_id = cursor.lastrowid
        db.commit()
        
        return jsonify({
            'message': 'Package créé avec succès',
            'package': {
                'id': package_id,
                'name': data['name'],
                'version': data['version']
            }
        }), 201
        
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Ce package existe déjà'}), 400
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
        
        if row:
            package = dict(row)
            
            # Récupérer les badges du package
            cursor.execute('''
                SELECT b.*
                FROM badges b
                JOIN badge_assignments ba ON b.id = ba.badge_id
                WHERE ba.package_id = ? AND b.is_active = 1
            ''', (package['id'],))
            
            badges = []
            for badge_row in cursor.fetchall():
                badge = dict(badge_row)
                badge['svg_url'] = f'https://zenv-hub.onrender.com/badge/svg/{badge["name"]}'
                badge['base64_url'] = f'https://zenv-hub.onrender.com/badge/base64/{badge["name"]}'
                badges.append(badge)
            
            package['badges'] = badges
            
            return jsonify({'package': package})
        else:
            return jsonify({'error': 'Package non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# Ajoute cette route dans ton app.py

@app.route('/api/packages/upload', methods=['POST'])
@token_required
def upload_package_file():
    """Uploader un fichier de package"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Aucun fichier fourni'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Nom de fichier vide'}), 400
        
        # Vérifier l'extension
        allowed_extensions = {'.whl', '.tar.gz', '.zip', '.egg'}
        if not any(file.filename.endswith(ext) for ext in allowed_extensions):
            return jsonify({'error': 'Type de fichier non supporté'}), 400
        
        # Récupérer les métadonnées du formulaire
        package_name = request.form.get('name')
        version = request.form.get('version')
        
        if not package_name or not version:
            return jsonify({'error': 'Nom et version du package requis'}), 400
        
        # Créer le répertoire pour le package
        package_dir = os.path.join(app.config['PACKAGE_DIR'], package_name)
        os.makedirs(package_dir, exist_ok=True)
        
        # Sauvegarder le fichier
        filename = f"{package_name}-{version}{os.path.splitext(file.filename)[1]}"
        filepath = os.path.join(package_dir, filename)
        file.save(filepath)
        
        # Calculer le hash
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        # Sauvegarder en base de données
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO releases (package_id, version, filename, file_size, file_hash)
            VALUES (
                (SELECT id FROM packages WHERE name = ?),
                ?, ?, ?, ?
            )
        ''', (package_name, version, filename, os.path.getsize(filepath), file_hash))
        
        db.commit()
        
        return jsonify({
            'message': 'Fichier uploadé avec succès',
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
        
        # Récupérer le fichier
        cursor.execute('''
            SELECT filename FROM releases r
            JOIN packages p ON r.package_id = p.id
            WHERE p.name = ? AND r.version = ?
        ''', (package_name, version))
        
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Package non trouvé'}), 404
        
        filename = row['filename']
        filepath = os.path.join(app.config['PACKAGE_DIR'], package_name, filename)
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        # Incrémenter le compteur de téléchargements
        cursor.execute('''
            UPDATE packages 
            SET downloads_count = downloads_count + 1 
            WHERE name = ?
        ''', (package_name,))
        db.commit()
        
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/files', methods=['GET'])
def list_package_files():
    """Lister tous les fichiers de packages disponibles"""
    packages_dir = app.config['PACKAGE_DIR']
    
    if not os.path.exists(packages_dir):
        return jsonify({'files': [], 'count': 0})
    
    files_list = []
    for package_name in os.listdir(packages_dir):
        package_dir = os.path.join(packages_dir, package_name)
        if os.path.isdir(package_dir):
            for filename in os.listdir(package_dir):
                filepath = os.path.join(package_dir, filename)
                if os.path.isfile(filepath):
                    files_list.append({
                        'package': package_name,
                        'filename': filename,
                        'size': os.path.getsize(filepath),
                        'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                        'download_url': f'https://zenv-hub.onrender.com/api/packages/download/{package_name}/{filename}'
                    })
    
    return jsonify({
        'files': files_list,
        'count': len(files_list)
    })
# ============================================================================
# INITIALISATION
# ============================================================================

def initialize_app():
    """Initialiser l'application"""
    print("🚀 Initialisation de Zenv Package Hub...")
    
    # Initialiser SQLite
    success = init_sqlite()
    if success:
        print("✅ SQLite initialisé avec succès")
    else:
        print("⚠️ SQLite déjà initialisé")
    
    print("🎉 Application prête à fonctionner!")

# ============================================================================
# HOOKS FLASK
# ============================================================================

@app.teardown_appcontext
def teardown_db(exception):
    """Fermer la base de données à la fin de la requête"""
    close_db()

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
