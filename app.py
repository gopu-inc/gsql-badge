"""
Zenv Package Hub - Version finale corrigée pour production
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
import psycopg2
from psycopg2.extras import RealDictCursor, DictCursor
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file, session, abort, Response
from flask_cors import CORS
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
import yaml
from packaging.version import parse as parse_version

# ============================================================================
# CONFIGURATION
# ============================================================================

# Configuration PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL', "postgresql://volve_user:odM5spc4DLMdEPJww834aDNE7c49J9bG@dpg-d4vpeu24d50c7385s840-a.oregon-postgres.render.com/volve?sslmode=require")

# Configuration GitHub
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "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")
GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/zenv")
GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
GITHUB_EMAIL = os.environ.get('GITHUB_EMAIL', "ceoseshell@gmail.com")
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package")

# Configuration JWT et sécurité
JWT_SECRET = os.environ.get('JWT_SECRET', "votre_super_secret_jwt_changez_moi_12345")
APP_SECRET = os.environ.get('APP_SECRET', "votre_app_secret_changez_moi_67890")

# Initialisation Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

app.config.update(
    SECRET_KEY=APP_SECRET,
    JWT_SECRET_KEY=JWT_SECRET,
    DATABASE_URL=DATABASE_URL,
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
# UTILITAIRES POSTGRESQL
# ============================================================================

def get_db_connection():
    """Établit une connexion à PostgreSQL"""
    try:
        conn = psycopg2.connect(app.config['DATABASE_URL'])
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"❌ Erreur connexion PostgreSQL: {e}")
        return None

def init_postgresql():
    """Initialise les tables PostgreSQL"""
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            print("❌ Impossible de se connecter à PostgreSQL")
            return False
            
        cur = conn.cursor()
        
        # Vérifier si la table usrs existe
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'usrs'
            )
        """)
        table_exists = cur.fetchone()[0]
        
        if not table_exists:
            print("🔄 Création des tables PostgreSQL...")
            
            # Table usrs
            cur.execute('''
                CREATE TABLE usrs (
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
                    avatar_url TEXT,
                    bio TEXT,
                    website TEXT
                )
            ''')
            
            # Table packages
            cur.execute('''
                CREATE TABLE packages (
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
                    usr_id INTEGER REFERENCES usrs(id) ON DELETE CASCADE,
                    downloads_count INTEGER DEFAULT 0,
                    is_private BOOLEAN DEFAULT FALSE,
                    language VARCHAR(20) DEFAULT 'python',
                    UNIQUE(name, version)
                )
            ''')
            
            # Table badges
            cur.execute('''
                CREATE TABLE badges (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL,
                    label VARCHAR(50) NOT NULL,
                    value VARCHAR(100) NOT NULL,
                    color VARCHAR(20) DEFAULT 'blue',
                    svg_content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by INTEGER REFERENCES usrs(id) ON DELETE SET NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    usage_count INTEGER DEFAULT 0
                )
            ''')
            
            # Table badge_assignments
            cur.execute('''
                CREATE TABLE badge_assignments (
                    id SERIAL PRIMARY KEY,
                    badge_id INTEGER REFERENCES badges(id) ON DELETE CASCADE,
                    package_id INTEGER REFERENCES packages(id) ON DELETE CASCADE,
                    usr_id INTEGER REFERENCES usrs(id) ON DELETE CASCADE,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_by INTEGER REFERENCES usrs(id) ON DELETE SET NULL,
                    UNIQUE(badge_id, package_id, usr_id)
                )
            ''')
            
            # Table releases
            cur.execute('''
                CREATE TABLE releases (
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
            
            # Table downloads
            cur.execute('''
                CREATE TABLE downloads (
                    id SERIAL PRIMARY KEY,
                    release_id INTEGER REFERENCES releases(id) ON DELETE CASCADE,
                    usr_id INTEGER REFERENCES usrs(id) ON DELETE SET NULL,
                    ip_address INET,
                    user_agent TEXT,
                    country VARCHAR(50),
                    download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    api_key VARCHAR(100)
                )
            ''')
            
            conn.commit()
            print("✅ Tables PostgreSQL créées avec succès")
            
            # Créer l'admin par défaut
            hashed_pw = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
            cur.execute('''
                INSERT INTO usrs (username, email, password, role, is_verified)
                VALUES ('admin', 'admin@zenvhub.com', %s, 'admin', TRUE)
                ON CONFLICT (username) DO NOTHING
            ''', (hashed_pw,))
            
            conn.commit()
            print("✅ Admin créé: admin / admin123")
        else:
            print("✅ Tables PostgreSQL existent déjà")
            
        return True
            
    except Exception as e:
        print(f"❌ Erreur initialisation PostgreSQL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if conn:
            cur.close()
            conn.close()

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
    """Processeur Markdown avancé"""
    
    @staticmethod
    def process_markdown(text: str) -> str:
        """Convertit Markdown en HTML"""
        if not text:
            return ""
        
        # Nettoyer
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Extensions Markdown
        extensions = [
            'markdown.extensions.fenced_code',
            'markdown.extensions.tables',
            'markdown.extensions.toc',
            'markdown.extensions.nl2br',
            'markdown.extensions.smarty',
            CodeHiliteExtension(
                linenums=False,
                pygments_style='monokai',
                css_class='codehilite'
            ),
            FencedCodeExtension()
        ]
        
        html = markdown.markdown(text, extensions=extensions)
        
        # Post-traitement
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
        
        # Dimensions
        label_width = max(len(label) * 6 + 10, 30)
        value_width = max(len(value) * 6 + 10, 30)
        total_width = label_width + value_width
        height = 20
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
        <svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{height}" role="img" aria-label="{label}: {value}">
            <title>{label}: {value}</title>
            
            <g>
                <!-- Partie label -->
                <rect width="{label_width}" height="{height}" fill="{color_hex}" rx="3"/>
                
                <!-- Partie value -->
                <rect x="{label_width}" width="{value_width}" height="{height}" fill="#555" rx="3"/>
                
                <!-- Texte label -->
                <text x="{label_width/2}" y="14" text-anchor="middle" fill="#fff" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11" font-weight="bold">
                    {label.upper()}
                </text>
                
                <!-- Texte value -->
                <text x="{label_width + value_width/2}" y="14" text-anchor="middle" fill="#fff" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11" font-weight="bold">
                    {value}
                </text>
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
# DÉCORATEURS D'AUTHENTIFICATION
# ============================================================================

def login_required(f):
    """Décorateur pour les routes nécessitant une authentification"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usr_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            flash('Veuillez vous connecter pour accéder à cette page', 'warning')
            return redirect(url_for('login'))
        
        token = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        elif 'access_token' in session:
            token = session['access_token']
        
        if not token:
            if request.is_json:
                return jsonify({'error': 'Token missing'}), 401
            flash('Session invalide, veuillez vous reconnecter', 'danger')
            session.clear()
            return redirect(url_for('login'))
        
        try:
            payload = SecurityUtils.verify_token(token)
            request.usr_id = payload['usr_id']
            request.usr_role = payload.get('role', 'user')
        except Exception as e:
            if request.is_json:
                return jsonify({'error': str(e)}), 401
            flash('Session expirée, veuillez vous reconnecter', 'danger')
            session.clear()
            return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Décorateur pour les routes admin"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            if request.is_json:
                return jsonify({'error': 'Admin access required'}), 403
            abort(403)
        
        request.usr_id = session['usr_id']
        request.usr_role = session['role']
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# FILTRES TEMPLATE
# ============================================================================

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    """Filtre de formatage de date"""
    if value is None:
        return ''
    
    if isinstance(value, str):
        try:
            # Essayer de parser la date
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S.%f']:
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
    """Tronque une chaîne"""
    if not s:
        return ''
    if len(s) <= length:
        return s
    return s[:length] + '...'

# ============================================================================
# ROUTES PRINCIPALES
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Packages récents
            cur.execute('''
                SELECT p.*, u.username as author_name
                FROM packages p
                LEFT JOIN usrs u ON p.usr_id = u.id
                WHERE p.is_private = FALSE
                ORDER BY p.created_at DESC
                LIMIT 6
            ''')
            recent_packages = cur.fetchall()
            
            # Statistiques
            cur.execute('SELECT COUNT(*) as total_usrs FROM usrs')
            total_usrs = cur.fetchone()['total_usrs'] or 0
            
            cur.execute('SELECT COUNT(*) as total_packages FROM packages WHERE is_private = FALSE')
            total_packages = cur.fetchone()['total_packages'] or 0
            
            cur.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
            total_downloads = cur.fetchone()['total_downloads'] or 0
            
            # Badges populaires
            cur.execute('''
                SELECT b.*, u.username as created_by_name
                FROM badges b
                LEFT JOIN usrs u ON b.created_by = u.id
                WHERE b.is_active = TRUE
                ORDER BY b.usage_count DESC
                LIMIT 4
            ''')
            popular_badges = cur.fetchall()
            
            cur.close()
            conn.close()
            
            return render_template('home.html',
                                recent_packages=recent_packages,
                                popular_badges=popular_badges,
                                total_usrs=total_usrs,
                                total_packages=total_packages,
                                total_downloads=total_downloads,
                                page='index')
    except Exception as e:
        print(f"⚠️ Erreur index: {e}")
    
    # Fallback si erreur
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
        
        conn = get_db_connection()
        if not conn:
            flash('Erreur de connexion à la base de données', 'danger')
            return render_template('login.html', page='login')
        
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute('''
                SELECT id, username, email, password, role 
                FROM usrs 
                WHERE username = %s OR email = %s
            ''', (username, username))
            
            usr = cur.fetchone()
            
            if usr and SecurityUtils.verify_password(password, usr['password']):
                # Mettre à jour last_login
                cur.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = %s', (usr['id'],))
                
                # Stocker en session
                session['usr_id'] = usr['id']
                session['username'] = usr['username']
                session['role'] = usr['role']
                
                conn.commit()
                
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Identifiants incorrects', 'danger')
                
        except Exception as e:
            flash(f'Erreur: {str(e)}', 'danger')
        finally:
            if conn:
                cur.close()
                conn.close()
    
    return render_template('login.html', page='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Inscription"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        # Validation
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html', page='register')
        
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('register.html', page='register')
        
        # Hasher le mot de passe
        hashed_pw = SecurityUtils.hash_password(password)
        
        conn = get_db_connection()
        if not conn:
            flash('Erreur de connexion à la base de données', 'danger')
            return render_template('register.html', page='register')
        
        try:
            cur = conn.cursor()
            
            cur.execute('''
                INSERT INTO usrs (username, email, password)
                VALUES (%s, %s, %s)
                RETURNING id
            ''', (username, email, hashed_pw))
            
            usr_id = cur.fetchone()[0]
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
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return redirect(url_for('index'))
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Infos usr
        cur.execute('SELECT username, email, role, created_at FROM usrs WHERE id = %s', 
                   (session['usr_id'],))
        usr = cur.fetchone()
        
        # Packages de l'usr
        cur.execute('''
            SELECT p.*
            FROM packages p
            WHERE p.usr_id = %s
            ORDER BY p.updated_at DESC
            LIMIT 10
        ''', (session['usr_id'],))
        packages = cur.fetchall()
        
        # Statistiques
        cur.execute('''
            SELECT 
                COUNT(DISTINCT p.id) as total_packages,
                COALESCE(SUM(p.downloads_count), 0) as total_downloads
            FROM packages p
            WHERE p.usr_id = %s
        ''', (session['usr_id'],))
        stats = cur.fetchone() or {'total_packages': 0, 'total_downloads': 0}
        
        # Badges de l'usr
        cur.execute('''
            SELECT b.*, ba.assigned_at
            FROM badges b
            JOIN badge_assignments ba ON b.id = ba.badge_id
            WHERE ba.usr_id = %s
            ORDER BY ba.assigned_at DESC
            LIMIT 5
        ''', (session['usr_id'],))
        usr_badges = cur.fetchall()
        
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
    finally:
        cur.close()
        conn.close()

@app.route('/packages')
def list_packages():
    """Liste des packages"""
    page = int(request.args.get('page', 1))
    per_page = 20
    search = request.args.get('q', '')
    language = request.args.get('lang', '')
    
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return render_template('packages.html', packages=[], page='packages')
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = '''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = FALSE
        '''
        
        params = []
        where_clauses = []
        
        if search:
            where_clauses.append('(p.name ILIKE %s OR p.description ILIKE %s)')
            params.extend([f'%{search}%', f'%{search}%'])
        
        if language:
            where_clauses.append('p.language = %s')
            params.append(language)
        
        if where_clauses:
            query += ' AND ' + ' AND '.join(where_clauses)
        
        query += ' ORDER BY p.updated_at DESC'
        
        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, offset])
        
        cur.execute(query, params)
        packages = cur.fetchall()
        
        # Total
        count_query = 'SELECT COUNT(*) FROM packages WHERE is_private = FALSE'
        if where_clauses:
            count_query += ' AND ' + ' AND '.join(where_clauses)
        
        cur.execute(count_query, params[:-2] if where_clauses else [])
        total = cur.fetchone()['count'] or 0
        
        # Langages disponibles
        cur.execute('SELECT DISTINCT language FROM packages WHERE language IS NOT NULL ORDER BY language')
        languages = [row['language'] for row in cur.fetchall()]
        
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
    finally:
        cur.close()
        conn.close()

@app.route('/package/<package_name>')
def package_detail(package_name):
    """Détails d'un package"""
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return redirect(url_for('list_packages'))
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Package
        cur.execute('''
            SELECT p.*, u.username as author_name, u.email as author_email
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.name = %s
        ''', (package_name,))
        
        package = cur.fetchone()
        
        if not package:
            flash('Package non trouvé', 'danger')
            return redirect(url_for('list_packages'))
        
        # Releases
        cur.execute('''
            SELECT * FROM releases
            WHERE package_id = %s
            ORDER BY version DESC
        ''', (package['id'],))
        
        releases = cur.fetchall()
        
        # Badges assignés
        cur.execute('''
            SELECT b.*
            FROM badges b
            JOIN badge_assignments ba ON b.id = ba.badge_id
            WHERE ba.package_id = %s
            ORDER BY b.name
        ''', (package['id'],))
        
        badges = cur.fetchall()
        
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
    finally:
        cur.close()
        conn.close()

@app.route('/badges')
def list_badges():
    """Liste des badges"""
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return render_template('badges.html', badges=[], page='badges')
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.is_active = TRUE
            ORDER BY b.usage_count DESC, b.name
        ''')
        
        badges = cur.fetchall()
        
        return render_template('badges.html', badges=badges, page='badges')
        
    except Exception as e:
        print(f"⚠️ Erreur list_badges: {e}")
        return render_template('badges.html', badges=[], page='badges')
    finally:
        cur.close()
        conn.close()

@app.route('/badge/<badge_name>')
def badge_detail(badge_name):
    """Détails d'un badge"""
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return redirect(url_for('list_badges'))
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.name = %s
        ''', (badge_name,))
        
        badge = cur.fetchone()
        
        if not badge:
            flash('Badge non trouvé', 'danger')
            return redirect(url_for('list_badges'))
        
        # Packages utilisant ce badge
        cur.execute('''
            SELECT p.*
            FROM packages p
            JOIN badge_assignments ba ON p.id = ba.package_id
            WHERE ba.badge_id = %s
            ORDER BY p.name
        ''', (badge['id'],))
        
        packages = cur.fetchall()
        
        return render_template('badge_detail.html',
                             badge=badge,
                             packages=packages,
                             page='badge_detail')
        
    except Exception as e:
        print(f"⚠️ Erreur badge_detail: {e}")
        flash('Erreur lors du chargement du badge', 'danger')
        return redirect(url_for('list_badges'))
    finally:
        cur.close()
        conn.close()

@app.route('/badge/generate', methods=['GET', 'POST'])
@login_required
def generate_badge():
    """Générer un nouveau badge"""
    if request.method == 'POST':
        name = request.form.get('name')
        label = request.form.get('label')
        value = request.form.get('value')
        color = request.form.get('color', 'blue')
        
        # Validation
        if not name or not label or not value:
            flash('Tous les champs sont requis', 'danger')
            return render_template('generate_badge.html', page='generate_badge')
        
        # Générer le SVG
        svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        
        # Sauvegarder sur disque
        BadgeGenerator.save_badge_svg(name, svg_content)
        
        conn = get_db_connection()
        if not conn:
            flash('Erreur de connexion à la base de données', 'danger')
            return render_template('generate_badge.html', page='generate_badge')
        
        try:
            cur = conn.cursor()
            
            # Sauvegarder en base
            cur.execute('''
                INSERT INTO badges (name, label, value, color, svg_content, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE 
                SET label = EXCLUDED.label,
                    value = EXCLUDED.value,
                    color = EXCLUDED.color,
                    svg_content = EXCLUDED.svg_content,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            ''', (name, label, value, color, svg_content, session['usr_id']))
            
            badge_id = cur.fetchone()[0]
            
            # Assigner à l'usr
            cur.execute('''
                INSERT INTO badge_assignments (badge_id, usr_id, assigned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            ''', (badge_id, session['usr_id'], session['usr_id']))
            
            conn.commit()
            
            flash('Badge créé avec succès!', 'success')
            return redirect(url_for('badge_detail', badge_name=name))
            
        except Exception as e:
            conn.rollback()
            flash(f'Erreur: {str(e)}', 'danger')
        finally:
            cur.close()
            conn.close()
    
    return render_template('generate_badge.html', page='generate_badge')

@app.route('/badge/svg/<badge_name>')
def serve_badge_svg(badge_name):
    """Servir un badge SVG"""
    badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
    
    if not os.path.exists(badge_path):
        # Générer un badge par défaut
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
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return render_template('admin_dashboard.html', page='admin_dashboard')
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Statistiques
        cur.execute('SELECT COUNT(*) as total_usrs FROM usrs')
        total_usrs = cur.fetchone()['total_usrs'] or 0
        
        cur.execute('SELECT COUNT(*) as total_packages FROM packages')
        total_packages = cur.fetchone()['total_packages'] or 0
        
        cur.execute('SELECT COUNT(*) as total_badges FROM badges')
        total_badges = cur.fetchone()['total_badges'] or 0
        
        cur.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
        total_downloads = cur.fetchone()['total_downloads'] or 0
        
        # Usrs récents
        cur.execute('SELECT id, username, email, role, created_at FROM usrs ORDER BY created_at DESC LIMIT 10')
        recent_usrs = cur.fetchall()
        
        # Packages récents
        cur.execute('''
            SELECT p.*, u.username as author_name
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 10
        ''')
        recent_packages = cur.fetchall()
        
        # Badges récents
        cur.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            ORDER BY b.created_at DESC
            LIMIT 10
        ''')
        recent_badges = cur.fetchall()
        
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
        flash('Erreur lors du chargement du dashboard admin', 'danger')
        return render_template('admin_dashboard.html', page='admin_dashboard')
    finally:
        cur.close()
        conn.close()

@app.route('/admin/badges', methods=['GET', 'POST'])
@admin_required
def admin_manage_badges():
    """Gestion des badges par l'admin"""
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return render_template('admin_manage_badges.html', badges=[], page='admin_manage_badges')
    
    if request.method == 'POST':
        action = request.form.get('action')
        badge_id = request.form.get('badge_id')
        
        if action == 'edit' and badge_id:
            name = request.form.get('name')
            label = request.form.get('label')
            value = request.form.get('value')
            color = request.form.get('color', 'blue')
            is_active = request.form.get('is_active') == 'on'
            
            try:
                # Générer nouveau SVG
                svg_content = BadgeGenerator.create_svg_badge(label, value, color)
                
                # Sauvegarder sur disque
                BadgeGenerator.save_badge_svg(name, svg_content)
                
                # Mettre à jour la base
                cur = conn.cursor()
                cur.execute('''
                    UPDATE badges 
                    SET name = %s, label = %s, value = %s, color = %s, 
                        svg_content = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (name, label, value, color, svg_content, is_active, badge_id))
                
                conn.commit()
                flash('Badge mis à jour avec succès', 'success')
                
            except Exception as e:
                conn.rollback()
                flash(f'Erreur: {str(e)}', 'danger')
            finally:
                cur.close()
        
        elif action == 'delete' and badge_id:
            try:
                cur = conn.cursor()
                cur.execute('DELETE FROM badges WHERE id = %s', (badge_id,))
                conn.commit()
                flash('Badge supprimé avec succès', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Erreur: {str(e)}', 'danger')
            finally:
                cur.close()
    
    # Récupérer tous les badges
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            ORDER BY b.name
        ''')
        
        badges = cur.fetchall()
        
        return render_template('admin_manage_badges.html', badges=badges, page='admin_manage_badges')
        
    except Exception as e:
        print(f"⚠️ Erreur admin_manage_badges: {e}")
        return render_template('admin_manage_badges.html', badges=[], page='admin_manage_badges')
    finally:
        cur.close()
        conn.close()

@app.route('/admin/badge/editor/<badge_id>')
@admin_required
def admin_badge_editor(badge_id):
    """Éditeur de badge pour admin"""
    conn = get_db_connection()
    if not conn:
        flash('Erreur de connexion à la base de données', 'danger')
        return redirect(url_for('admin_manage_badges'))
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('SELECT * FROM badges WHERE id = %s', (badge_id,))
        badge = cur.fetchone()
        
        if not badge:
            flash('Badge non trouvé', 'danger')
            return redirect(url_for('admin_manage_badges'))
        
        return render_template('admin_badge_editor.html', badge=badge, page='admin_badge_editor')
        
    except Exception as e:
        print(f"⚠️ Erreur admin_badge_editor: {e}")
        flash('Erreur lors du chargement du badge', 'danger')
        return redirect(url_for('admin_manage_badges'))
    finally:
        cur.close()
        conn.close()

# ============================================================================
# ROUTES API
# ============================================================================

@app.route('/api/v1/packages')
def api_list_packages():
    """API: Liste des packages"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database unavailable'}), 503
            
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)
        search = request.args.get('q', '')
        language = request.args.get('lang', '')
        
        query = '''
            SELECT p.id, p.name, p.version, p.description, p.language,
                   p.downloads_count, p.created_at, u.username as author
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            WHERE p.is_private = FALSE
        '''
        
        params = []
        where_clauses = []
        
        if search:
            where_clauses.append('(p.name ILIKE %s OR p.description ILIKE %s)')
            params.extend([f'%{search}%', f'%{search}%'])
        
        if language:
            where_clauses.append('p.language = %s')
            params.append(language)
        
        if where_clauses:
            query += ' AND ' + ' AND '.join(where_clauses)
        
        query += ' ORDER BY p.created_at DESC'
        
        # Pagination
        offset = (page - 1) * per_page
        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, offset])
        
        cur.execute(query, params)
        packages = cur.fetchall()
        
        # Total
        count_query = 'SELECT COUNT(*) FROM packages WHERE is_private = FALSE'
        if where_clauses:
            count_query += ' AND ' + ' AND '.join(where_clauses)
        
        cur.execute(count_query, params[:-2] if where_clauses else [])
        total = cur.fetchone()['count'] or 0
        
        cur.close()
        conn.close()
        
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

@app.route('/api/v1/badges')
def api_list_badges():
    """API: Liste des badges"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database unavailable'}), 503
            
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
            SELECT name, label, value, color, usage_count
            FROM badges
            WHERE is_active = TRUE
            ORDER BY name
        ''')
        
        badges = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return jsonify({'badges': badges})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# CONTEXT PROCESSOR
# ============================================================================

@app.context_processor
def inject_variables():
    """Injecte des variables dans tous les templates"""
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
    """Page 404"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page non trouvée</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #dc3545; }
        </style>
    </head>
    <body>
        <h1>404 - Page non trouvée</h1>
        <p>La page que vous recherchez n'existe pas.</p>
        <a href="/">Retour à l'accueil</a>
    </body>
    </html>
    """, 404

@app.errorhandler(500)
def internal_server_error(e):
    """Erreur interne du serveur"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Erreur interne du serveur</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #dc3545; }
        </style>
    </head>
    <body>
        <h1>500 - Erreur interne du serveur</h1>
        <p>Une erreur s'est produite. Veuillez réessayer plus tard.</p>
        <a href="/">Retour à l'accueil</a>
    </body>
    </html>
    """, 500

@app.errorhandler(403)
def forbidden(e):
    """Accès interdit"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>403 - Accès interdit</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #ffc107; }
        </style>
    </head>
    <body>
        <h1>403 - Accès interdit</h1>
        <p>Vous n'avez pas la permission d'accéder à cette page.</p>
        <a href="/">Retour à l'accueil</a>
    </body>
    </html>
    """, 403

# ============================================================================
# INITIALISATION
# ============================================================================

def initialize_app():
    """Fonction d'initialisation"""
    print("🚀 Initialisation de Zenv Package Hub...")
    
    # Initialiser PostgreSQL
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🔄 Tentative {attempt + 1}/{max_retries} d'initialisation PostgreSQL...")
            success = init_postgresql()
            if success:
                print("✅ PostgreSQL initialisé avec succès")
                break
            else:
                print(f"⚠️ Échec de l'initialisation PostgreSQL (tentative {attempt + 1})")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
        except Exception as e:
            print(f"❌ Erreur lors de la tentative {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
    
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
        else:
            print(f"⚠️  Répertoire {dir_name} manquant: {dir_path}")
    
    print("🎉 Application prête à fonctionner!")

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

# Initialiser l'application
initialize_app()

if __name__ == '__main__':
    # En développement
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'True') == 'True'
    )
