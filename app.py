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
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "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")
GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/zenv")
GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
GITHUB_EMAIL = os.environ.get('GITHUB_EMAIL', "ceoseshell@gmail.com")
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package-data")

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
                # Clone du dépôt
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
        except Exception as e:
            print(f"⚠️ Erreur configuration Git: {e}")
    
    @staticmethod
    def backup_database():
        """Sauvegarder la base de données dans Git"""
        if not os.path.exists(app.config['GIT_REPO_PATH']):
            return False
        
        try:
            # Copier la base de données
            db_path = app.config['DATABASE_PATH']
            backup_path = os.path.join(app.config['GIT_REPO_PATH'], 'zenv_hub.db')
            
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_path)
            
            # Ajouter au Git
            repo_path = app.config['GIT_REPO_PATH']
            subprocess.run(['git', 'add', '.'], cwd=repo_path, check=True)
            
            # Commit
            commit_message = f"Backup automatique - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(['git', 'commit', '-m', commit_message], 
                         cwd=repo_path, check=True)
            
            # Push vers GitHub
            subprocess.run(['git', 'push', 'origin', GITHUB_BRANCH], 
                         cwd=repo_path, check=True)
            
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
                             cwd=repo_path, check=True)
                
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
        
        return render_template('home.html',
                             recent_packages=recent_packages,
                             popular_badges=popular_badges,
                             total_usrs=total_usrs,
                             total_packages=total_packages,
                             total_downloads=total_downloads,
                             page='index')
        
    except Exception as e:
        print(f"⚠️ Erreur index: {e}")
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
        usr = dict(cursor.fetchone())
        
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
        stats = dict(cursor.fetchone()) if cursor.fetchone() else {'total_packages': 0, 'total_downloads': 0}
        
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
        
        return render_template('dashboard.html',
                             usr=usr,
                             packages=packages,
                             stats=stats,
                             usr_badges=usr_badges,
                             page='dashboard')
        
    except Exception as e:
        print(f"⚠️ Erreur dashboard: {e}")
        flash('Erreur lors du chargement du tableau de bord', 'danger')
        return redirect(url_for('index'))

@app.route('/packages')
def list_packages():
    """Liste des packages"""
    page = int(request.args.get('page', 1))
    per_page = 20
    search = request.args.get('q', '')
    language = request.args.get('lang', '')
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        query = '''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
        '''
        
        params = []
        where_clauses = []
        
        if search:
            where_clauses.append('(p.name LIKE ? OR p.description LIKE ?)')
            params.extend([f'%{search}%', f'%{search}%'])
        
        if language:
            where_clauses.append('p.language = ?')
            params.append(language)
        
        if where_clauses:
            query += ' AND ' + ' AND '.join(where_clauses)
        
        query += ' ORDER BY p.updated_at DESC'
        
        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT ? OFFSET ?'
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        packages = [dict(row) for row in cursor.fetchall()]
        
        # Total
        count_query = 'SELECT COUNT(*) FROM packages WHERE is_private = 0'
        if where_clauses:
            count_query += ' AND ' + ' AND '.join(where_clauses)
        
        cursor.execute(count_query, params[:-2] if where_clauses else [])
        total = cursor.fetchone()[0] or 0
        
        # Langages disponibles
        cursor.execute('SELECT DISTINCT language FROM packages WHERE language IS NOT NULL ORDER BY language')
        languages = [row[0] for row in cursor.fetchall()]
        
        return render_template('packages.html',
                             packages=packages,
                             page_num=page,
                             per_page=per_page,
                             total=total,
                             total_pages=(total + per_page - 1) // per_page if per_page > 0 else 0,
                             search=search,
                             language=language,
                             languages=languages,
                             page='packages')
        
    except Exception as e:
        print(f"⚠️ Erreur list_packages: {e}")
        return render_template('packages.html', packages=[], page='packages')

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
            flash('Package non trouvé', 'danger')
            return redirect(url_for('list_packages'))
        
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
        
        return render_template('package_detail.html',
                             package=package,
                             releases=releases,
                             badges=badges,
                             readme_html=readme_html,
                             page='package_detail')
        
    except Exception as e:
        print(f"⚠️ Erreur package_detail: {e}")
        flash('Erreur lors du chargement du package', 'danger')
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
        
        return render_template('badges.html', badges=badges, page='badges')
        
    except Exception as e:
        print(f"⚠️ Erreur list_badges: {e}")
        return render_template('badges.html', badges=[], page='badges')

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
# ROUTES ADMIN
# ============================================================================

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
        recent_usrs = [dict(row) for row in cursor.fetchall()]
        
        # Packages récents
        cursor.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 10
        ''')
        recent_packages = [dict(row) for row in cursor.fetchall()]
        
        # Badges récents
        cursor.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            ORDER BY b.created_at DESC
            LIMIT 10
        ''')
        recent_badges = [dict(row) for row in cursor.fetchall()]
        
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
        print(f"⚠️ Erreur admin_dashboard: {e}")
        return render_template('admin_dashboard.html', page='admin_dashboard')

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/v1/packages')
def api_list_packages():
    """API: Liste des packages"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)
        search = request.args.get('q', '')
        language = request.args.get('lang', '')
        
        query = '''
            SELECT p.id, p.name, p.version, p.description, p.language,
                   p.downloads_count, p.created_at, u.username as author
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = 0
        '''
        
        params = []
        where_clauses = []
        
        if search:
            where_clauses.append('(p.name LIKE ? OR p.description LIKE ?)')
            params.extend([f'%{search}%', f'%{search}%'])
        
        if language:
            where_clauses.append('p.language = ?')
            params.append(language)
        
        if where_clauses:
            query += ' AND ' + ' AND '.join(where_clauses)
        
        query += ' ORDER BY p.created_at DESC'
        
        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT ? OFFSET ?'
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        packages = [dict(row) for row in cursor.fetchall()]
        
        # Total
        count_query = 'SELECT COUNT(*) FROM packages WHERE is_private = 0'
        if where_clauses:
            count_query += ' AND ' + ' AND '.join(where_clauses)
        
        cursor.execute(count_query, params[:-2] if where_clauses else [])
        total = cursor.fetchone()[0] or 0
        
        return jsonify({
            'packages': packages,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page non trouvée</title>
        <style>body { font-family: Arial; text-align: center; padding: 50px; }</style>
    </head>
    <body>
        <h1>404 - Page non trouvée</h1>
        <p><a href="/">Retour à l'accueil</a></p>
    </body>
    </html>
    """, 404

@app.errorhandler(500)
def internal_server_error(e):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Erreur serveur</title>
        <style>body { font-family: Arial; text-align: center; padding: 50px; }</style>
    </head>
    <body>
        <h1>500 - Erreur serveur</h1>
        <p><a href="/">Retour à l'accueil</a></p>
    </body>
    </html>
    """, 500

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
    
    # Sauvegarder dans Git après certaines actions importantes
    if request and request.endpoint in ['login', 'register', 'generate_badge']:
        GitManager.backup_database()

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
