"""
Zenv Package Hub - Version avec Git sur branche package
"""

import os
import json
import re
import hashlib
import base64
import secrets
import jwt
import bcrypt
import tempfile
import shutil
import tarfile
import zipfile
import io
import uuid
import sqlite3
import subprocess
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
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "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")
GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/zenv")
GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
GITHUB_EMAIL = os.environ.get('GITHUB_EMAIL', "ceoseshell@gmail.com")
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package")  # Branche package

# Configuration JWT et sécurité
JWT_SECRET = os.environ.get('JWT_SECRET', "votre_super_secret_jwt_changez_moi_12345")
APP_SECRET = os.environ.get('APP_SECRET', "votre_app_secret_changez_moi_67890")

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
        # Créer la base de données si elle n'existe pas
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
# UTILITAIRES GIT - BRANCHE PACKAGE
# ============================================================================

class GitManager:
    """Gestionnaire Git pour la branche package"""
    
    @staticmethod
    def init_git_repo():
        """Initialiser le dépôt Git sur la branche package"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            print(f"🔄 Clonage du dépôt Git {GITHUB_REPO} (branche: {GITHUB_BRANCH})...")
            try:
                # Clone du dépôt avec la branche package
                subprocess.run([
                    'git', 'clone',
                    '-b', GITHUB_BRANCH,  # Spécifier la branche
                    f'https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git',
                    repo_path
                ], check=True, capture_output=True, text=True)
                print(f"✅ Dépôt Git cloné (branche: {GITHUB_BRANCH})")
            except Exception as e:
                print(f"❌ Erreur clonage Git: {e}")
                # Créer un nouveau dépôt local
                os.makedirs(repo_path, exist_ok=True)
                subprocess.run(['git', 'init'], cwd=repo_path, check=True)
                subprocess.run(['git', 'checkout', '-b', GITHUB_BRANCH], cwd=repo_path, check=True)
                print(f"✅ Dépôt Git initialisé localement (branche: {GITHUB_BRANCH})")
        else:
            # Vérifier si on est sur la bonne branche
            try:
                result = subprocess.run(['git', 'branch', '--show-current'], 
                                      cwd=repo_path, capture_output=True, text=True)
                current_branch = result.stdout.strip()
                if current_branch != GITHUB_BRANCH:
                    print(f"🔄 Changement vers la branche {GITHUB_BRANCH}...")
                    subprocess.run(['git', 'checkout', GITHUB_BRANCH], cwd=repo_path, check=True)
                    print(f"✅ Branchée sur {GITHUB_BRANCH}")
            except Exception as e:
                print(f"⚠️ Erreur vérification branche: {e}")
        
        # Configurer Git
        try:
            subprocess.run(['git', 'config', 'user.name', GITHUB_USERNAME], 
                         cwd=repo_path, check=True)
            subprocess.run(['git', 'config', 'user.email', GITHUB_EMAIL], 
                         cwd=repo_path, check=True)
            subprocess.run(['git', 'config', 'pull.rebase', 'false'], 
                         cwd=repo_path, check=True)
        except Exception as e:
            print(f"⚠️ Erreur configuration Git: {e}")
    
    @staticmethod
    def backup_database():
        """Sauvegarder la base de données dans Git (branche package)"""
        repo_path = app.config['GIT_REPO_PATH']
        
        if not os.path.exists(repo_path):
            return False
        
        try:
            # Copier la base de données
            db_path = app.config['DATABASE_PATH']
            backup_path = os.path.join(repo_path, 'zenv_hub.db')
            
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_path)
            
            # Ajouter au Git
            subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True, capture_output=True)
            
            # Commit
            commit_message = f"Backup automatique - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(['git', 'commit', '-m', commit_message], 
                         cwd=repo_path, check=True, capture_output=True)
            
            # Pull d'abord pour récupérer les changements
            try:
                subprocess.run(['git', 'pull', 'origin', GITHUB_BRANCH, '--no-edit'], 
                             cwd=repo_path, check=True, capture_output=True)
            except:
                print("⚠️ Pull échoué, continuation...")
            
            # Push vers GitHub sur la branche package
            subprocess.run(['git', 'push', 'origin', GITHUB_BRANCH], 
                         cwd=repo_path, check=True, capture_output=True)
            
            print(f"✅ Base de données sauvegardée dans Git (branche: {GITHUB_BRANCH})")
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde Git: {e}")
            return False
    
    @staticmethod
    def restore_database():
        """Restaurer la base de données depuis Git (branche package)"""
        repo_path = app.config['GIT_REPO_PATH']
        backup_path = os.path.join(repo_path, 'zenv_hub.db')
        
        if os.path.exists(repo_path):
            try:
                # Pull les dernières modifications de la branche package
                subprocess.run(['git', 'pull', 'origin', GITHUB_BRANCH], 
                             cwd=repo_path, check=True, capture_output=True)
                
                if os.path.exists(backup_path):
                    # Restaurer la base de données
                    db_path = app.config['DATABASE_PATH']
                    shutil.copy2(backup_path, db_path)
                    
                    print(f"✅ Base de données restaurée depuis Git (branche: {GITHUB_BRANCH})")
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
            <g>
                <rect width="{label_width}" height="{height}" fill="{color_hex}" rx="3"/>
                <rect x="{label_width}" width="{value_width}" height="{height}" fill="#555" rx="3"/>
                <text x="{label_width/2}" y="14" text-anchor="middle" fill="#fff" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11" font-weight="bold">{label.upper()}</text>
                <text x="{label_width + value_width/2}" y="14" text-anchor="middle" fill="#fff" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11" font-weight="bold">{value}</text>
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
# HEALTH CHECK
# ============================================================================

@app.route('/health')
def health_check():
    """Health check endpoint pour Render"""
    try:
        # Vérifier la base de données
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT 1')
        cursor.fetchone()
        
        # Vérifier les répertoires
        required_dirs = [app.config['PACKAGE_DIR'], app.config['SVG_DIR']]
        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                return jsonify({
                    'status': 'error',
                    'message': f'Directory missing: {dir_path}'
                }), 500
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'zenv-package-hub',
            'database': 'connected',
            'git_branch': GITHUB_BRANCH,
            'version': '1.0.0'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# ============================================================================
# ROUTES PRINCIPALES - CORRIGÉES
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
        rows = cursor.fetchall()
        recent_packages = [dict(row) for row in rows]
        
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
        rows = cursor.fetchall()
        popular_badges = [dict(row) for row in rows]
        
        return render_template('home.html',
                             recent_packages=recent_packages,
                             popular_badges=popular_badges,
                             total_usrs=total_usrs,
                             total_packages=total_packages,
                             total_downloads=total_downloads,
                             page='index')
        
    except Exception as e:
        print(f"⚠️ Erreur index: {e}")
        import traceback
        traceback.print_exc()
        return render_template('home.html',
                             recent_packages=[],
                             popular_badges=[],
                             total_usrs=0,
                             total_packages=0,
                             total_downloads=0,
                             page='index')

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
            
            if row and SecurityUtils.verify_password(password, row[3]):  # row[3] = password
                session['usr_id'] = row[0]
                session['username'] = row[1]
                session['role'] = row[4]
                
                # Mettre à jour last_login
                cursor.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (row[0],))
                db.commit()
                
                # Sauvegarder dans Git
                GitManager.backup_database()
                
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Identifiants incorrects', 'danger')
                
        except Exception as e:
            print(f"❌ Erreur login: {e}")
            flash(f'Erreur: {str(e)}', 'danger')
    
    return render_template('login.html', page='login')

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
            return render_template('register.html', page='register')
        
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('register.html', page='register')
        
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
            print(f"❌ Erreur register: {e}")
            flash(f'Erreur: {str(e)}', 'danger')
    
    return render_template('register.html', page='register')

@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Infos usr
        cursor.execute('SELECT username, email, role, created_at FROM usrs WHERE id = ?', 
                      (session['usr_id'],))
        row = cursor.fetchone()
        if row:
            usr = {
                'username': row[0],
                'email': row[1],
                'role': row[2],
                'created_at': row[3]
            }
        else:
            usr = {}
        
        # Packages de l'usr
        cursor.execute('''
            SELECT p.*
            FROM packages p
            WHERE p.usr_id = ?
            ORDER BY p.updated_at DESC
            LIMIT 10
        ''', (session['usr_id'],))
        rows = cursor.fetchall()
        packages = []
        for row in rows:
            packages.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'version': row[3],
                'author': row[4],
                'downloads_count': row[15] or 0,
                'is_private': row[16],
                'language': row[17],
                'created_at': row[12]
            })
        
        # Statistiques
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT p.id) as total_packages,
                COALESCE(SUM(p.downloads_count), 0) as total_downloads
            FROM packages p
            WHERE p.usr_id = ?
        ''', (session['usr_id'],))
        row = cursor.fetchone()
        stats = {
            'total_packages': row[0] if row else 0,
            'total_downloads': row[1] if row else 0
        }
        
        # Badges de l'usr
        cursor.execute('''
            SELECT b.*, ba.assigned_at
            FROM badges b
            JOIN badge_assignments ba ON b.id = ba.badge_id
            WHERE ba.usr_id = ?
            ORDER BY ba.assigned_at DESC
            LIMIT 5
        ''', (session['usr_id'],))
        rows = cursor.fetchall()
        usr_badges = []
        for row in rows:
            usr_badges.append({
                'id': row[0],
                'name': row[1],
                'label': row[2],
                'value': row[3],
                'color': row[4],
                'assigned_at': row[10] if len(row) > 10 else None
            })
        
        return render_template('dashboard.html',
                             usr=usr,
                             packages=packages,
                             stats=stats,
                             usr_badges=usr_badges,
                             page='dashboard')
        
    except Exception as e:
        print(f"❌ Erreur dashboard: {e}")
        import traceback
        traceback.print_exc()
        flash('Erreur lors du chargement du tableau de bord', 'danger')
        return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Tableau de bord admin"""
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
        
        # Usrs récents
        cursor.execute('SELECT id, username, email, role, created_at FROM usrs ORDER BY created_at DESC LIMIT 10')
        rows = cursor.fetchall()
        recent_usrs = []
        for row in rows:
            recent_usrs.append({
                'id': row[0],
                'username': row[1],
                'email': row[2],
                'role': row[3],
                'created_at': row[4]
            })
        
        # Packages récents
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 10
        ''')
        rows = cursor.fetchall()
        recent_packages = []
        for row in rows:
            recent_packages.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'version': row[3],
                'author_name': row[18] if len(row) > 18 else None,
                'downloads_count': row[15] or 0,
                'is_private': row[16],
                'created_at': row[12]
            })
        
        # Badges récents
        cursor.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            ORDER BY b.created_at DESC
            LIMIT 10
        ''')
        rows = cursor.fetchall()
        recent_badges = []
        for row in rows:
            recent_badges.append({
                'id': row[0],
                'name': row[1],
                'label': row[2],
                'value': row[3],
                'color': row[4],
                'created_by_name': row[10] if len(row) > 10 else None,
                'usage_count': row[9] or 0
            })
        
        return render_template('admin_dashboard.html',
                             total_usrs=total_usrs,
                             total_packages=total_packages,
                             total_badges=total_badges,
                             total_downloads=total_downloads,
                             recent_usrs=recent_usrs,
                             recent_packages=recent_packages,
                             recent_badges=recent_badges,
                             page='admin_dashboard')
        
    except Exception as e:
        print(f"❌ Erreur admin_dashboard: {e}")
        import traceback
        traceback.print_exc()
        flash('Erreur lors du chargement du dashboard admin', 'danger')
        return render_template('error.html', 
                             error='Erreur interne du serveur',
                             message='Veuillez réessayer plus tard.'), 500

@app.route('/badge/generate', methods=['GET', 'POST'])
@login_required
def generate_badge():
    """Générer un nouveau badge"""
    if request.method == 'POST':
        name = request.form.get('name')
        label = request.form.get('label')
        value = request.form.get('value')
        color = request.form.get('color', 'blue')
        
        if not name or not label or not value:
            flash('Tous les champs sont requis', 'danger')
            return render_template('generate_badge.html', page='generate_badge')
        
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
            
            flash('Badge créé avec succès!', 'success')
            return redirect(url_for('list_badges'))
            
        except Exception as e:
            print(f"❌ Erreur generate_badge: {e}")
            flash(f'Erreur: {str(e)}', 'danger')
    
    return render_template('generate_badge.html', page='generate_badge')

@app.route('/badge/svg/<badge_name>')
def serve_badge_svg(badge_name):
    """Servir un badge SVG"""
    badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
    
    if not os.path.exists(badge_path):
        svg_content = BadgeGenerator.create_svg_badge("Not Found", "404", "red")
        return Response(svg_content, mimetype='image/svg+xml')
    
    return send_file(badge_path, mimetype='image/svg+xml')

# ============================================================================
# AUTRES ROUTES SIMPLIFIÉES
# ============================================================================

@app.route('/packages')
def list_packages():
    """Liste des packages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
            ORDER BY p.updated_at DESC
        ''')
        rows = cursor.fetchall()
        packages = []
        for row in rows:
            packages.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'version': row[3],
                'author': row[4],
                'author_name': row[18] if len(row) > 18 else None,
                'downloads_count': row[15] or 0,
                'language': row[17],
                'created_at': row[12]
            })
        
        return render_template('packages.html', packages=packages, page='packages')
        
    except Exception as e:
        print(f"⚠️ Erreur list_packages: {e}")
        return render_template('packages.html', packages=[], page='packages')

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
            ORDER BY b.usage_count DESC
        ''')
        rows = cursor.fetchall()
        badges = []
        for row in rows:
            badges.append({
                'id': row[0],
                'name': row[1],
                'label': row[2],
                'value': row[3],
                'color': row[4],
                'created_by_name': row[10] if len(row) > 10 else None,
                'usage_count': row[9] or 0
            })
        
        return render_template('badges.html', badges=badges, page='badges')
        
    except Exception as e:
        print(f"⚠️ Erreur list_badges: {e}")
        return render_template('badges.html', badges=[], page='badges')

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
        'email': 'ceoseshell@gmail.com',
        'git_branch': GITHUB_BRANCH
    }

# ============================================================================
# GESTION DES ERREURS
# ============================================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', 
                         error='404 - Page non trouvée',
                         message='La page que vous recherchez n\'existe pas.'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html',
                         error='500 - Erreur interne du serveur',
                         message='Une erreur s\'est produite. Veuillez réessayer plus tard.'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html',
                         error='403 - Accès interdit',
                         message='Vous n\'avez pas la permission d\'accéder à cette page.'), 403

# ============================================================================
# TEMPLATE ERROR.HTML
# ============================================================================

@app.route('/error')
def error_page():
    """Page d'erreur de test"""
    return render_template('error.html',
                         error='Test Error',
                         message='Ceci est une page d\'erreur de test.')

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
    
    # Initialiser Git (branche package)
    try:
        GitManager.init_git_repo()
        print(f"✅ Git initialisé (branche: {GITHUB_BRANCH})")
        
        # Essayer de restaurer depuis Git
        if GitManager.restore_database():
            print(f"✅ Données restaurées depuis Git (branche: {GITHUB_BRANCH})")
        else:
            print("ℹ️  Aucune donnée à restaurer depuis Git")
    except Exception as e:
        print(f"⚠️ Erreur Git: {e}")
    
    # Vérifier les répertoires
    for dir_name, dir_path in [
        ('Packages', app.config['PACKAGE_DIR']),
        ('Uploads', app.config['UPLOAD_DIR']),
        ('Builds', app.config['BUILD_DIR']),
        ('Badges', app.config['BADGES_DIR']),
        ('SVG', app.config['SVG_DIR']),
        ('Templates', 'templates'),
        ('Static', 'static')
    ]:
        if os.path.exists(dir_path):
            print(f"✅ Répertoire {dir_name}: {dir_path}")
    
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
