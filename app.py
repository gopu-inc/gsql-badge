"""
Zenv Package Hub - Version SQLite avec synchronisation Git
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

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file, session, abort, Response, g
from flask_cors import CORS
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
import yaml
from packaging.version import parse as parse_version

# ============================================================================
# CONFIGURATION
# ============================================================================

# Configuration SQLite
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'zenv_hub.db')
GIT_REPO_PATH = os.path.join(BASE_DIR, 'zenv-data')

# Configuration GitHub
GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "main"

# Configuration JWT et sécurité
JWT_SECRET = "votre_super_secret_jwt_changez_moi_12345"
APP_SECRET = "votre_app_secret_changez_moi_67890"

# Initialisation Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

app.config.update(
    SECRET_KEY=APP_SECRET,
    JWT_SECRET_KEY=JWT_SECRET,
    DATABASE_PATH=DATABASE_PATH,
    GIT_REPO_PATH=GIT_REPO_PATH,
    PACKAGE_DIR=os.path.join(os.path.dirname(__file__), 'packages'),
    UPLOAD_DIR=os.path.join(os.path.dirname(__file__), 'uploads'),
    BUILD_DIR=os.path.join(os.path.dirname(__file__), 'builds'),
    BADGES_DIR=os.path.join(os.path.dirname(__file__), 'badges'),
    SVG_DIR=os.path.join(os.path.dirname(__file__), 'static', 'badges'),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    JWT_ACCESS_TOKEN_EXPIRES=3600,
    JWT_REFRESH_TOKEN_EXPIRES=2592000,
    BCRYPT_ROUNDS=12
)

# Créer les répertoires
for dir_path in [app.config['PACKAGE_DIR'], app.config['UPLOAD_DIR'], 
                 app.config['BUILD_DIR'], app.config['BADGES_DIR'],
                 app.config['SVG_DIR'], 'templates', 'static']:
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
        
        # Vérifier si les tables existent
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
                    verification_token TEXT,
                    reset_token TEXT,
                    reset_expires TIMESTAMP,
                    last_login TIMESTAMP,
                    avatar_url TEXT,
                    bio TEXT,
                    website TEXT
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
                    keywords TEXT,
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
            
            # Table badges
            cursor.execute('''
                CREATE TABLE badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    label TEXT NOT NULL,
                    value TEXT NOT NULL,
                    color TEXT DEFAULT 'blue',
                    svg_content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    usage_count INTEGER DEFAULT 0,
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
                    lfs_tracked BOOLEAN DEFAULT 0,
                    UNIQUE(package_id, version),
                    FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE CASCADE
                )
            ''')
            
            # Table downloads
            cursor.execute('''
                CREATE TABLE downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    release_id INTEGER,
                    usr_id INTEGER,
                    ip_address TEXT,
                    user_agent TEXT,
                    country TEXT,
                    download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    api_key TEXT,
                    FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE,
                    FOREIGN KEY (usr_id) REFERENCES usrs(id) ON DELETE SET NULL
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
# UTILITAIRES GIT
# ============================================================================

class GitManager:
    """Gestionnaire Git pour la synchronisation des données"""
    
    @staticmethod
    def init_git_repo():
        """Initialiser le dépôt Git pour les données"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            print(f"🔄 Clonage du dépôt Git {GITHUB_REPO}...")
            try:
                # Clone du dépôt avec token
                subprocess.run([
                    'git', 'clone',
                    f'https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git',
                    repo_path
                ], check=True, capture_output=True)
                print("✅ Dépôt Git cloné avec succès")
            except Exception as e:
                print(f"❌ Erreur clonage Git: {e}")
                # Créer un nouveau dépôt local
                os.makedirs(repo_path, exist_ok=True)
                subprocess.run(['git', 'init'], cwd=repo_path, check=True)
                print("✅ Dépôt Git initialisé localement")
        
        # Configurer Git
        try:
            subprocess.run(['git', 'config', 'user.name', GITHUB_USERNAME], 
                         cwd=repo_path, check=True)
            subprocess.run(['git', 'config', 'user.email', GITHUB_EMAIL], 
                         cwd=repo_path, check=True)
            
            # Vérifier et créer la branche si nécessaire
            result = subprocess.run(['git', 'branch', '--show-current'], 
                                  cwd=repo_path, capture_output=True, text=True)
            current_branch = result.stdout.strip()
            
            if current_branch != GITHUB_BRANCH:
                subprocess.run(['git', 'checkout', '-b', GITHUB_BRANCH], 
                             cwd=repo_path, capture_output=True)
                
        except Exception as e:
            print(f"⚠️ Erreur configuration Git: {e}")
    
    @staticmethod
    def backup_database():
        """Sauvegarder la base de données dans Git"""
        if not os.path.exists(app.config['GIT_REPO_PATH']):
            return False
        
        try:
            repo_path = app.config['GIT_REPO_PATH']
            
            # Copier la base de données
            db_path = app.config['DATABASE_PATH']
            backup_path = os.path.join(repo_path, 'zenv_hub.db')
            
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_path)
            
            # Ajouter au Git
            subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
            
            # Commit
            commit_message = f"Backup automatique - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(['git', 'commit', '-m', commit_message], 
                         cwd=repo_path, check=True, capture_output=True)
            
            # Push vers GitHub
            subprocess.run(['git', 'push', '-u', 'origin', GITHUB_BRANCH, '--force'], 
                         cwd=repo_path, check=True, capture_output=True)
            
            print("✅ Base de données sauvegardée dans Git")
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde Git: {e}")
            return False
    
    @staticmethod
    def restore_database():
        """Restaurer la base de données depuis Git"""
        repo_path = app.config['GIT_REPO_PATH']
        backup_path = os.path.join(repo_path, 'zenv_hub.db')
        
        if os.path.exists(backup_path):
            try:
                # Pull les dernières modifications
                subprocess.run(['git', 'pull', 'origin', GITHUB_BRANCH], 
                             cwd=repo_path, check=True, capture_output=True)
                
                # Restaurer la base de données
                db_path = app.config['DATABASE_PATH']
                shutil.copy2(backup_path, db_path)
                
                print("✅ Base de données restaurée depuis Git")
                return True
                
            except Exception as e:
                print(f"⚠️ Erreur restauration Git: {e}")
                return False
        
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
        
        refresh_payload = {
            'usr_id': usr_id,
            'type': 'refresh',
            'exp': datetime.utcnow() + timedelta(seconds=app.config['JWT_REFRESH_TOKEN_EXPIRES']),
            'iat': datetime.utcnow(),
            'jti': str(uuid.uuid4())
        }
        
        access_token = jwt.encode(access_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        refresh_token = jwt.encode(refresh_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
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

class MarkdownProcessor:
    """Processeur Markdown"""
    
    @staticmethod
    def process_markdown(text: str) -> str:
        """Convertit Markdown en HTML"""
        if not text:
            return ""
        
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        extensions = [
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'markdown.extensions.toc',
            'markdown.extensions.nl2br',
            CodeHiliteExtension(
                linenums=False,
                pygments_style='monokai',
                css_class='codehilite'
            )
        ]
        
        html = markdown.markdown(text, extensions=extensions)
        html = html.replace('<table>', '<table class="table table-dark table-striped">')
        html = html.replace('<blockquote>', '<blockquote class="blockquote">')
        
        return html

class BadgeGenerator:
    """Générateur de badges SVG"""
    
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
    def save_badge_svg(badge_name: str, svg_content: str) -> str:
        """Sauvegarde un badge SVG"""
        badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
        with open(badge_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        return badge_path
    
    @staticmethod
    def get_badge_url(badge_name: str) -> str:
        """Retourne l'URL d'un badge"""
        return f"/static/badges/{badge_name}.svg"

# ============================================================================
# DÉCORATEURS
# ============================================================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usr_id' not in session:
            flash('Veuillez vous connecter', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# FILTRES TEMPLATE
# ============================================================================

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    if value is None:
        return ''
    
    if isinstance(value, str):
        try:
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%d']:
                try:
                    value = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            if isinstance(value, str):
                return value
        except Exception:
            return value
    
    if isinstance(value, datetime):
        return value.strftime(format)
    
    return str(value)

@app.template_filter('truncate')
def truncate_filter(s, length=100):
    if not s:
        return ''
    return s[:length] + '...' if len(s) > length else s

# ============================================================================
# ROUTES PRINCIPALES
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Packages récents
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
            ORDER BY p.created_at DESC
            LIMIT 6
        ''')
        recent_packages = [dict(row) for row in cursor.fetchall()]
        
        # Statistiques
        cursor.execute('SELECT COUNT(*) as total_usrs FROM usrs')
        total_usrs = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) as total_packages FROM packages WHERE is_private = 0')
        total_packages = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
        total_downloads = cursor.fetchone()[0] or 0
        
        # Badges populaires
        cursor.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.is_active = 1
            ORDER BY b.usage_count DESC
            LIMIT 4
        ''')
        popular_badges = [dict(row) for row in cursor.fetchall()]
        
        # Page d'accueil simple
        packages_html = ''
        for pkg in recent_packages:
            packages_html += f'''
            <div style="border:1px solid #ddd;padding:15px;margin:10px 0;border-radius:5px;">
                <h3>{pkg["name"]} v{pkg["version"]}</h3>
                <p>{pkg.get("description", "Pas de description")}</p>
                <p><small>Auteur: {pkg["author_name"] or "Inconnu"} | Téléchargements: {pkg["downloads_count"]}</small></p>
            </div>
            '''
        
        badges_html = ''
        for badge in popular_badges:
            badges_html += f'<img src="/badge/svg/{badge["name"]}" alt="{badge["label"]}: {badge["value"]}" style="margin:5px;">'
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; border-radius: 10px; text-align: center; margin-bottom: 30px; }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin-bottom: 30px; }}
                .stat-card {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .stat-value {{ font-size: 2em; font-weight: bold; color: #667eea; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: #667eea; text-decoration: none; font-weight: bold; }}
                .nav a:hover {{ text-decoration: underline; }}
                .section {{ margin-bottom: 40px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🚀 Zenv Package Hub</h1>
                <p>Le hub officiel des packages Zenv</p>
                <div class="nav">
                    <a href="/packages">📦 Packages</a>
                    <a href="/badges">🏅 Badges</a>
                    {'<a href="/dashboard">👤 Tableau de bord</a>' if 'usr_id' in session else '<a href="/login">🔐 Connexion</a>'}
                </div>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{total_usrs}</div>
                    <div>Utilisateurs</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_packages}</div>
                    <div>Packages</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_downloads}</div>
                    <div>Téléchargements</div>
                </div>
            </div>
            
            <div class="section">
                <h2>✨ Packages récents</h2>
                {packages_html if packages_html else '<p>Aucun package pour le moment.</p>'}
                <p style="text-align:center;"><a href="/packages">Voir tous les packages →</a></p>
            </div>
            
            <div class="section">
                <h2>🏅 Badges populaires</h2>
                <div style="text-align:center;">
                    {badges_html if badges_html else '<p>Aucun badge pour le moment.</p>'}
                </div>
                <p style="text-align:center;"><a href="/badges">Voir tous les badges →</a></p>
            </div>
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur index: {e}")
        import traceback
        traceback.print_exc()
        # Page d'accueil de secours
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Zenv Package Hub</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                h1 { color: #667eea; }
                .nav { margin: 20px 0; }
                .nav a { margin: 0 10px; color: #667eea; text-decoration: none; }
            </style>
        </head>
        <body>
            <h1>🚀 Zenv Package Hub</h1>
            <p>Bienvenue sur le hub de packages Zenv</p>
            <div class="nav">
                <a href="/login">Connexion</a>
                <a href="/register">Inscription</a>
            </div>
        </body>
        </html>
        '''

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Connexion"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
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
                session['usr_id'] = row['id']
                session['username'] = row['username']
                session['role'] = row['role']
                
                # Mettre à jour last_login
                cursor.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (row['id'],))
                db.commit()
                
                # Sauvegarder dans Git
                GitManager.backup_database()
                
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Identifiants incorrects', 'danger')
                
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'danger')
    
    # Page de connexion simple
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Connexion - Zenv Package Hub</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; }
            input { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 4px; }
            button { background: #28a745; color: white; padding: 12px; border: none; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; }
            .alert { padding: 10px; margin: 10px 0; border-radius: 4px; }
            .alert-danger { background: #f8d7da; color: #721c24; }
            .nav { text-align: center; margin-top: 20px; }
            .nav a { color: #667eea; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1 style="text-align:center;color:#667eea;">🔐 Connexion</h1>
        <form method="POST">
            <div class="form-group">
                <label>Nom d'utilisateur ou Email:</label>
                <input type="text" name="username" required>
            </div>
            
            <div class="form-group">
                <label>Mot de passe:</label>
                <input type="password" name="password" required>
            </div>
            
            <button type="submit">Se connecter</button>
        </form>
        
        <div class="nav">
            <p>Pas de compte ? <a href="/register">S'inscrire</a></p>
            <p><a href="/">← Retour à l'accueil</a></p>
        </div>
    </body>
    </html>
    '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Inscription"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('register'))
        
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return redirect(url_for('register'))
        
        hashed_pw = SecurityUtils.hash_password(password)
        
        try:
            db = get_db()
            cursor = db.cursor()
            
            cursor.execute('''
                INSERT INTO usrs (username, email, password)
                VALUES (?, ?, ?)
            ''', (username, email, hashed_pw))
            
            db.commit()
            
            # Sauvegarder dans Git
            GitManager.backup_database()
            
            flash('Inscription réussie! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('login'))
            
        except sqlite3.IntegrityError as e:
            if 'username' in str(e):
                flash('Ce nom d\'utilisateur existe déjà', 'danger')
            elif 'email' in str(e):
                flash('Cet email est déjà utilisé', 'danger')
            else:
                flash('Erreur lors de l\'inscription', 'danger')
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'danger')
    
    # Page d'inscription simple
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Inscription - Zenv Package Hub</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; }
            input { width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 4px; }
            button { background: #007bff; color: white; padding: 12px; border: none; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; }
            .nav { text-align: center; margin-top: 20px; }
            .nav a { color: #667eea; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1 style="text-align:center;color:#007bff;">📝 Inscription</h1>
        <form method="POST">
            <div class="form-group">
                <label>Nom d'utilisateur:</label>
                <input type="text" name="username" required>
            </div>
            
            <div class="form-group">
                <label>Email:</label>
                <input type="email" name="email" required>
            </div>
            
            <div class="form-group">
                <label>Mot de passe:</label>
                <input type="password" name="password" required>
            </div>
            
            <div class="form-group">
                <label>Confirmer le mot de passe:</label>
                <input type="password" name="confirm_password" required>
            </div>
            
            <button type="submit">S'inscrire</button>
        </form>
        
        <div class="nav">
            <p>Déjà inscrit ? <a href="/login">Se connecter</a></p>
            <p><a href="/">← Retour à l'accueil</a></p>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    """Tableau de bord"""
    if 'usr_id' not in session:
        return redirect(url_for('login'))
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Infos usr
        cursor.execute('SELECT username, email, role, created_at FROM usrs WHERE id = ?', 
                      (session['usr_id'],))
        row = cursor.fetchone()
        if row:
            usr = dict(row)
        else:
            return redirect(url_for('logout'))
        
        # Packages de l'usr
        cursor.execute('''
            SELECT p.*
            FROM packages p
            WHERE p.usr_id = ?
            ORDER BY p.updated_at DESC
            LIMIT 10
        ''', (session['usr_id'],))
        packages = [dict(row) for row in cursor.fetchall()]
        
        # Statistiques
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT p.id) as total_packages,
                COALESCE(SUM(p.downloads_count), 0) as total_downloads
            FROM packages p
            WHERE p.usr_id = ?
        ''', (session['usr_id'],))
        
        stats_row = cursor.fetchone()
        if stats_row:
            stats = dict(stats_row)
        else:
            stats = {'total_packages': 0, 'total_downloads': 0}
        
        # Badges de l'usr
        cursor.execute('''
            SELECT b.*, ba.assigned_at
            FROM badges b
            JOIN badge_assignments ba ON b.id = ba.badge_id
            WHERE ba.usr_id = ?
            ORDER BY ba.assigned_at DESC
            LIMIT 5
        ''', (session['usr_id'],))
        usr_badges = [dict(row) for row in cursor.fetchall()]
        
        # Générer HTML
        packages_html = ''
        for pkg in packages:
            packages_html += f'''
            <tr>
                <td>{pkg['name']}</td>
                <td>{pkg['version']}</td>
                <td>{pkg['downloads_count']}</td>
                <td>{pkg['created_at'][:10] if pkg['created_at'] else ''}</td>
            </tr>
            '''
        
        badges_html = ''
        for badge in usr_badges:
            badges_html += f'<img src="/badge/svg/{badge["name"]}" alt="{badge["label"]}: {badge["value"]}" style="margin:5px;">'
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Tableau de bord - Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
                .stat-card {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .stat-value {{ font-size: 2em; font-weight: bold; color: #28a745; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: white; text-decoration: none; font-weight: bold; }}
                .section {{ margin-bottom: 40px; padding: 20px; background: #f8f9fa; border-radius: 8px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #dee2e6; }}
                th {{ background: #e9ecef; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>👤 Tableau de bord</h1>
                <p>Bienvenue, <strong>{usr['username']}</strong> !</p>
                <div class="nav">
                    <a href="/">🏠 Accueil</a>
                    <a href="/packages">📦 Packages</a>
                    <a href="/badges">🏅 Badges</a>
                    <a href="/badge/generate">✨ Créer un badge</a>
                    <a href="/logout">🚪 Déconnexion</a>
                </div>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{stats['total_packages']}</div>
                    <div>Packages</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{stats['total_downloads']}</div>
                    <div>Téléchargements</div>
                </div>
            </div>
            
            <div class="section">
                <h2>📦 Mes Packages</h2>
                {'<table><tr><th>Nom</th><th>Version</th><th>Téléchargements</th><th>Date</th></tr>' + packages_html + '</table>' if packages_html else '<p>Vous n\'avez pas encore de packages.</p>'}
            </div>
            
            <div class="section">
                <h2>🏅 Mes Badges</h2>
                <div style="text-align:center;">
                    {badges_html if badges_html else '<p>Vous n\'avez pas encore de badges.</p>'}
                </div>
            </div>
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur dashboard: {e}")
        return redirect(url_for('index'))

@app.route('/packages')
def list_packages():
    """Liste des packages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Récupérer tous les packages publics
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
            ORDER BY p.created_at DESC
        ''')
        packages = [dict(row) for row in cursor.fetchall()]
        
        # Compter le total
        cursor.execute('SELECT COUNT(*) as total FROM packages WHERE is_private = 0')
        total = cursor.fetchone()[0] or 0
        
        # Générer HTML
        packages_html = ''
        for pkg in packages:
            packages_html += f'''
            <div style="border:1px solid #ddd;padding:20px;margin:15px 0;border-radius:8px;background:white;">
                <h3 style="margin-top:0;">{pkg['name']} v{pkg['version']}</h3>
                <p>{pkg.get('description', 'Pas de description')}</p>
                <p><small>👤 Auteur: {pkg['author_name'] or 'Inconnu'} | 📥 Téléchargements: {pkg['downloads_count']} | 📅 Créé le: {pkg['created_at'][:10] if pkg['created_at'] else 'N/A'}</small></p>
                <p><a href="/package/{pkg['name']}" style="color:#667eea;text-decoration:none;">🔍 Voir détails →</a></p>
            </div>
            '''
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Packages - Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #fd7e14 0%, #ffc107 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; text-align: center; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: white; text-decoration: none; font-weight: bold; }}
                .package-count {{ text-align: center; color: #6c757d; margin-bottom: 30px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📦 Packages Zenv</h1>
                <p>Découvrez tous les packages disponibles</p>
                <div class="nav">
                    <a href="/">🏠 Accueil</a>
                    <a href="/badges">🏅 Badges</a>
                    {'<a href="/dashboard">👤 Tableau de bord</a>' if 'usr_id' in session else '<a href="/login">🔐 Connexion</a>'}
                </div>
            </div>
            
            <div class="package-count">
                <h3>{total} packages disponibles</h3>
            </div>
            
            {packages_html if packages_html else '<div style="text-align:center;padding:40px;color:#6c757d;"><h3>📦 Aucun package disponible pour le moment.</h3></div>'}
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur list_packages: {e}")
        return redirect(url_for('index'))

@app.route('/package/<package_name>')
def package_detail(package_name):
    """Détails d'un package"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Package
        cursor.execute('''
            SELECT p.*, u.username as author_name, u.email as author_email
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.name = ?
        ''', (package_name,))
        
        row = cursor.fetchone()
        if not row:
            return '''
            <!DOCTYPE html>
            <html>
            <head><title>Package non trouvé</title></head>
            <body>
                <h1>Package non trouvé</h1>
                <p><a href="/packages">← Retour aux packages</a></p>
            </body>
            </html>
            '''
        
        package = dict(row)
        
        # Releases
        cursor.execute('''
            SELECT * FROM releases
            WHERE package_id = ?
            ORDER BY version DESC
        ''', (package['id'],))
        
        releases = [dict(row) for row in cursor.fetchall()]
        
        # Badges assignés
        cursor.execute('''
            SELECT b.*
            FROM badges b
            JOIN badge_assignments ba ON b.id = ba.badge_id
            WHERE ba.package_id = ?
            ORDER BY b.name
        ''', (package['id'],))
        
        badges = [dict(row) for row in cursor.fetchall()]
        
        # Convertir README en HTML
        readme_html = MarkdownProcessor.process_markdown(package.get('readme', ''))
        
        # Générer HTML
        releases_html = ''
        if releases:
            for release in releases:
                releases_html += f'''
                <div style="border:1px solid #dee2e6;padding:15px;margin:10px 0;border-radius:5px;background:#f8f9fa;">
                    <strong>Version {release['version']}</strong>
                    <p>📦 Taille: {release['file_size'] or 'N/A'} | 📥 Téléchargements: {release['download_count']}</p>
                </div>
                '''
        
        badges_html = ''
        if badges:
            for badge in badges:
                badges_html += f'<img src="/badge/svg/{badge["name"]}" alt="{badge["label"]}: {badge["value"]}" style="margin:5px;">'
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>{package['name']} - Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #f8f9fa; padding: 30px; border-radius: 10px; margin-bottom: 30px; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: #667eea; text-decoration: none; font-weight: bold; }}
                .section {{ margin-bottom: 30px; padding: 20px; background: white; border: 1px solid #dee2e6; border-radius: 8px; }}
                code {{ background: #f8f9fa; padding: 5px 10px; border-radius: 4px; font-family: monospace; }}
                .badges {{ text-align: center; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="nav">
                <a href="/">🏠 Accueil</a>
                <a href="/packages">📦 Packages</a>
                <a href="/badges">🏅 Badges</a>
                {'<a href="/dashboard">👤 Tableau de bord</a>' if 'usr_id' in session else '<a href="/login">🔐 Connexion</a>'}
            </div>
            
            <div class="header">
                <h1>{package['name']} v{package['version']}</h1>
                <p style="font-size:1.2em;">{package.get('description', '')}</p>
                <p><small>👤 Auteur: {package['author_name'] or 'Inconnu'} | 📥 Téléchargements: {package['downloads_count']} | 📅 Créé le: {package['created_at'][:10] if package['created_at'] else ''}</small></p>
            </div>
            
            <div class="badges">
                {badges_html if badges_html else '<p>🏅 Aucun badge pour ce package.</p>'}
            </div>
            
            <div class="section">
                <h2>📦 Installation</h2>
                <p>Utilisez pip pour installer ce package:</p>
                <code>pip install {package['name']}</code>
            </div>
            
            <div class="section">
                <h2>📄 Versions disponibles</h2>
                {releases_html if releases_html else '<p>📦 Aucune version disponible.</p>'}
            </div>
            
            <div class="section">
                <h2>📖 Documentation</h2>
                <div>{readme_html if readme_html else '<p>📄 Aucune documentation disponible.</p>'}</div>
            </div>
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur package_detail: {e}")
        return redirect(url_for('list_packages'))

@app.route('/badges')
def list_badges():
    """Liste des badges"""
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
        
        badges = [dict(row) for row in cursor.fetchall()]
        
        # Générer HTML
        badges_html = ''
        for badge in badges:
            badges_html += f'''
            <div style="border:1px solid #dee2e6;padding:20px;margin:15px 0;border-radius:8px;background:white;text-align:center;">
                <img src="/badge/svg/{badge['name']}" alt="{badge['label']}: {badge['value']}" style="margin-bottom:15px;">
                <h3 style="margin-top:0;">{badge['name']}</h3>
                <p><strong>{badge['label']}</strong>: {badge['value']}</p>
                <p><small>👤 Créé par: {badge['created_by_name'] or 'Inconnu'} | 🔢 Utilisations: {badge['usage_count']}</small></p>
            </div>
            '''
        
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Badges - Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #6f42c1 0%, #9f5f9f 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; text-align: center; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: white; text-decoration: none; font-weight: bold; }}
                .badge-count {{ text-align: center; color: #6c757d; margin-bottom: 30px; }}
                .create-badge {{ text-align: center; margin: 30px 0; }}
                .create-badge a {{ display: inline-block; padding: 12px 24px; background: #28a745; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏅 Badges Zenv</h1>
                <p>Découvrez tous les badges disponibles</p>
                <div class="nav">
                    <a href="/">🏠 Accueil</a>
                    <a href="/packages">📦 Packages</a>
                    {'<a href="/dashboard">👤 Tableau de bord</a>' if 'usr_id' in session else '<a href="/login">🔐 Connexion</a>'}
                </div>
            </div>
            
            <div class="badge-count">
                <h3>{len(badges)} badges disponibles</h3>
            </div>
            
            {badges_html if badges_html else '<div style="text-align:center;padding:40px;color:#6c757d;"><h3>🏅 Aucun badge disponible pour le moment.</h3></div>'}
            
            {'<div class="create-badge"><a href="/badge/generate">✨ Créer un nouveau badge</a></div>' if 'usr_id' in session else ''}
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur list_badges: {e}")
        return redirect(url_for('index'))

@app.route('/badge/generate', methods=['GET', 'POST'])
def generate_badge():
    """Générer un nouveau badge"""
    if 'usr_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        label = request.form.get('label')
        value = request.form.get('value')
        color = request.form.get('color', 'blue')
        
        if not name or not label or not value:
            return '''
            <!DOCTYPE html>
            <html>
            <head><title>Erreur</title></head>
            <body>
                <h1>Erreur</h1>
                <p>Tous les champs sont requis</p>
                <p><a href="/badge/generate">← Retour</a></p>
            </body>
            </html>
            '''
        
        # Générer le SVG
        svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        BadgeGenerator.save_badge_svg(name, svg_content)
        
        try:
            db = get_db()
            cursor = db.cursor()
            
            # Sauvegarder en base
            cursor.execute('''
                INSERT INTO badges (name, label, value, color, svg_content, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE 
                SET label = excluded.label,
                    value = excluded.value,
                    color = excluded.color,
                    svg_content = excluded.svg_content,
                    updated_at = CURRENT_TIMESTAMP
            ''', (name, label, value, color, svg_content, session['usr_id']))
            
            badge_id = cursor.lastrowid
            
            # Assigner à l'usr
            cursor.execute('''
                INSERT OR IGNORE INTO badge_assignments (badge_id, usr_id, assigned_by)
                VALUES (?, ?, ?)
            ''', (badge_id, session['usr_id'], session['usr_id']))
            
            db.commit()
            
            # Sauvegarder dans Git
            GitManager.backup_database()
            
            return f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Badge créé - Zenv Package Hub</title>
                <style>
                    body {{ font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; text-align: center; }}
                    .success {{ color: #28a745; }}
                    img {{ margin: 20px; }}
                    .nav {{ margin-top: 30px; }}
                    .nav a {{ margin: 0 10px; color: #667eea; text-decoration: none; }}
                </style>
            </head>
            <body>
                <h1 class="success">✅ Badge créé avec succès!</h1>
                <img src="/badge/svg/{name}" alt="{label}: {value}">
                <p><strong>{name}</strong>: {label} - {value}</p>
                <div class="nav">
                    <a href="/badges">🏅 Voir tous les badges</a>
                    <a href="/badge/generate">✨ Créer un autre badge</a>
                </div>
            </body>
            </html>
            '''
            
        except Exception as e:
            return f'''
            <!DOCTYPE html>
            <html>
            <head><title>Erreur</title></head>
            <body>
                <h1>Erreur</h1>
                <p>Erreur lors de la création du badge: {str(e)}</p>
                <p><a href="/badge/generate">← Retour</a></p>
            </body>
            </html>
            '''
    
    # Page de génération de badge
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Créer un badge - Zenv Package Hub</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, select { width: 100%; padding: 12px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 4px; font-size: 16px; }
            button { background: #007bff; color: white; padding: 14px; border: none; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; font-weight: bold; }
            .nav { text-align: center; margin-top: 30px; }
            .nav a { margin: 0 10px; color: #667eea; text-decoration: none; }
            .header { text-align: center; margin-bottom: 30px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1 style="color:#007bff;">✨ Créer un badge</h1>
        </div>
        
        <form method="POST">
            <div class="form-group">
                <label>Nom du badge (unique):</label>
                <input type="text" name="name" placeholder="ex: version" required>
            </div>
            
            <div class="form-group">
                <label>Label (texte gauche):</label>
                <input type="text" name="label" placeholder="ex: version" required>
            </div>
            
            <div class="form-group">
                <label>Valeur (texte droite):</label>
                <input type="text" name="value" placeholder="ex: 1.0.0" required>
            </div>
            
            <div class="form-group">
                <label>Couleur:</label>
                <select name="color">
                    <option value="blue">🔵 Bleu</option>
                    <option value="green">🟢 Vert</option>
                    <option value="red">🔴 Rouge</option>
                    <option value="orange">🟠 Orange</option>
                    <option value="yellow">🟡 Jaune</option>
                    <option value="purple">🟣 Violet</option>
                    <option value="gray">⚪ Gris</option>
                </select>
            </div>
            
            <button type="submit">Créer le badge</button>
        </form>
        
        <div class="nav">
            <a href="/badges">← Retour aux badges</a>
            <a href="/dashboard">👤 Tableau de bord</a>
        </div>
    </body>
    </html>
    '''

@app.route('/badge/svg/<badge_name>')
def serve_badge_svg(badge_name):
    """Servir un badge SVG"""
    badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
    
    if not os.path.exists(badge_path):
        # Générer un badge par défaut si non trouvé
        svg_content = BadgeGenerator.create_svg_badge("Not Found", "404", "red")
        return Response(svg_content, mimetype='image/svg+xml')
    
    return send_file(badge_path, mimetype='image/svg+xml')

@app.route('/admin')
def admin_dashboard():
    """Tableau de bord admin"""
    if 'usr_id' not in session or session.get('role') != 'admin':
        abort(403)
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Statistiques
        cursor.execute('SELECT COUNT(*) as total_usrs FROM usrs')
        total_usrs = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) as total_packages FROM packages')
        total_packages = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) as total_badges FROM badges')
        total_badges = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
        total_downloads = cursor.fetchone()[0] or 0
        
        # Page admin simple
        return f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin - Zenv Package Hub</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #dc3545 0%, #e4606d 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; text-align: center; }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 20px; margin-bottom: 30px; }}
                .stat-card {{ background: white; border: 1px solid #dee2e6; border-radius: 8px; padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .stat-value {{ font-size: 2em; font-weight: bold; color: #dc3545; }}
                .nav {{ text-align: center; margin: 20px 0; }}
                .nav a {{ margin: 0 10px; color: white; text-decoration: none; font-weight: bold; }}
                .admin-warning {{ background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; padding: 15px; border-radius: 5px; margin-bottom: 20px; text-align: center; }}
                .actions {{ text-align: center; margin: 30px 0; }}
                .actions a {{ display: inline-block; margin: 10px; padding: 12px 24px; background: #6c757d; color: white; text-decoration: none; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏛️ Administration</h1>
                <p>Zone réservée aux administrateurs</p>
                <div class="nav">
                    <a href="/">🏠 Accueil</a>
                    <a href="/dashboard">👤 Tableau de bord</a>
                    <a href="/logout">🚪 Déconnexion</a>
                </div>
            </div>
            
            <div class="admin-warning">
                ⚠️ Zone réservée aux administrateurs
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{total_usrs}</div>
                    <div>Utilisateurs</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_packages}</div>
                    <div>Packages</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_badges}</div>
                    <div>Badges</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_downloads}</div>
                    <div>Téléchargements</div>
                </div>
            </div>
            
            <div class="actions">
                <a href="/packages">📦 Gérer les packages</a>
                <a href="/badges">🏅 Gérer les badges</a>
            </div>
        </body>
        </html>
        '''
        
    except Exception as e:
        print(f"⚠️ Erreur admin_dashboard: {e}")
        return redirect(url_for('index'))

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/v1/packages')
def api_list_packages():
    """API: Liste des packages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT p.id, p.name, p.version, p.description, p.language,
                   p.downloads_count, p.created_at, u.username as author
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
            ORDER BY p.created_at DESC
            LIMIT 50
        ''')
        
        packages = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'status': 'success',
            'data': {
                'packages': packages,
                'count': len(packages)
            }
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/badges')
def api_list_badges():
    """API: Liste des badges"""
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
        
        badges = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'status': 'success',
            'data': {
                'badges': badges,
                'count': len(badges)
            }
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================================
# CONTEXT PROCESSOR
# ============================================================================

@app.context_processor
def inject_variables():
    return {
        'now': datetime.now(),
        'app_name': 'Zenv Package Hub',
        'github_url': 'https://github.com/gopu-inc/zenv',
        'discord_url': 'https://discord.gg/qWx5DszrC',
        'email': 'ceoseshell@gmail.com'
    }

# ============================================================================
# GESTION DES ERREURS
# ============================================================================

@app.errorhandler(404)
def page_not_found(e):
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page non trouvée</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                text-align: center; 
                padding: 50px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
            }
            h1 { font-size: 3em; margin-bottom: 20px; }
            a { 
                color: white; 
                text-decoration: none;
                border: 2px solid white;
                padding: 10px 20px;
                border-radius: 5px;
                margin-top: 20px;
                display: inline-block;
            }
            a:hover { background: white; color: #667eea; }
        </style>
    </head>
    <body>
        <h1>404 - Page non trouvée</h1>
        <p>La page que vous cherchez n'existe pas.</p>
        <a href="/">🏠 Retour à l'accueil</a>
    </body>
    </html>
    ''', 404

@app.errorhandler(500)
def internal_server_error(e):
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Erreur serveur</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                text-align: center; 
                padding: 50px;
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                color: white;
                height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
            }
            h1 { font-size: 3em; margin-bottom: 20px; }
            a { 
                color: white; 
                text-decoration: none;
                border: 2px solid white;
                padding: 10px 20px;
                border-radius: 5px;
                margin-top: 20px;
                display: inline-block;
            }
            a:hover { background: white; color: #f5576c; }
        </style>
    </head>
    <body>
        <h1>500 - Erreur serveur</h1>
        <p>Une erreur interne s'est produite.</p>
        <a href="/">🏠 Retour à l'accueil</a>
    </body>
    </html>
    ''', 500

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
    
    # Initialiser Git
    GitManager.init_git_repo()
    
    # Essayer de restaurer depuis Git
    GitManager.restore_database()
    
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
