"""
Zenv Package Hub - Version complète avec PostgreSQL, badges SVG et support multi-langages
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
# CONFIGURATION - SIMPLIFIÉE
# ============================================================================

# Configuration PostgreSQL (à remplacer par vos variables)
DATABASE_URL = "postgresql://volve_user:odM5spc4DLMdEPJww834aDNE7c49J9bG@dpg-d4vpeu24d50c7385s840-a.oregon-postgres.render.com/volve?sslmode=require"

# Configuration GitHub
GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "package"

# Configuration JWT et sécurité
JWT_SECRET = "votre_super_secret_jwt_changez_moi_12345"
BCRYPT_SALT = bcrypt.gensalt(rounds=12)
APP_SECRET = "votre_app_secret_changez_moi_67890"

app = Flask(__name__)
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
                 app.config['SVG_DIR']]:
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
        raise

def init_postgresql():
    """Initialise les tables PostgreSQL avec usrs au lieu de users"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Table usrs (simplifiée)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS usrs (
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
                website TEXT,
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
                usr_id INTEGER REFERENCES usrs(id) ON DELETE CASCADE,
                downloads_count INTEGER DEFAULT 0,
                is_private BOOLEAN DEFAULT FALSE,
                language VARCHAR(20) DEFAULT 'python',
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
        
        # Table des badges
        cur.execute('''
            CREATE TABLE IF NOT EXISTS badges (
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
        
        # Table des badges assignés
        cur.execute('''
            CREATE TABLE IF NOT EXISTS badge_assignments (
                id SERIAL PRIMARY KEY,
                badge_id INTEGER REFERENCES badges(id) ON DELETE CASCADE,
                package_id INTEGER REFERENCES packages(id) ON DELETE CASCADE,
                usr_id INTEGER REFERENCES usrs(id) ON DELETE CASCADE,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                assigned_by INTEGER REFERENCES usrs(id) ON DELETE SET NULL,
                UNIQUE(badge_id, package_id, usr_id)
            )
        ''')
        
        # Table des téléchargements
        cur.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
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
        
        # Table des statistiques
        cur.execute('''
            CREATE TABLE IF NOT EXISTS stats_daily (
                id SERIAL PRIMARY KEY,
                date DATE UNIQUE NOT NULL,
                total_downloads INTEGER DEFAULT 0,
                unique_downloaders INTEGER DEFAULT 0,
                new_packages INTEGER DEFAULT 0,
                new_usrs INTEGER DEFAULT 0,
                badge_generations INTEGER DEFAULT 0
            )
        ''')
        
        # Index pour les performances
        cur.execute('CREATE INDEX IF NOT EXISTS idx_usrs_username ON usrs(username)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_usrs_email ON usrs(email)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_packages_name ON packages(name)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_packages_usr_id ON packages(usr_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_packages_language ON packages(language)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_badges_name ON badges(name)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_releases_package_id ON releases(package_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_downloads_download_time ON downloads(download_time)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_badge_assignments_package_id ON badge_assignments(package_id)')
        
        # Créer l'admin par défaut si non existant
        cur.execute("SELECT COUNT(*) FROM usrs WHERE username = 'admin'")
        if cur.fetchone()[0] == 0:
            hashed_pw = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
            cur.execute('''
                INSERT INTO usrs (username, email, password, role, is_verified)
                VALUES ('admin', 'admin@zenvhub.com', %s, 'admin', TRUE)
            ''', (hashed_pw,))
            print("✅ Admin créé: admin / admin123")
        
        conn.commit()
        print("✅ Tables PostgreSQL initialisées avec succès")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Erreur initialisation PostgreSQL: {e}")
        raise
    finally:
        cur.close()
        conn.close()

# ============================================================================
# UTILITAIRES AMÉLIORÉS
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
    """Processeur Markdown avancé avec support multi-langages"""
    
    # Mots-clés par langage pour la détection
    LANGUAGE_KEYWORDS = {
        'zenv': ['==>', 'zncv.', 'zen[', 'apend[', '{{', '}}', '~'],
        'python': ['import ', 'def ', 'class ', 'from ', 'return ', 'print('],
        'docker': ['FROM ', 'RUN ', 'COPY ', 'CMD ', 'EXPOSE ', 'ENV '],
        'bash': ['#!/bin/bash', '#!/bin/sh', 'echo ', 'export ', 'sudo '],
        'javascript': ['function ', 'const ', 'let ', 'console.log', 'export '],
        'html': ['<!DOCTYPE', '<html', '<div ', '<script ', '<style '],
        'css': ['{', '}', ':', ';', '.class', '#id'],
        'sql': ['SELECT ', 'INSERT ', 'UPDATE ', 'DELETE ', 'CREATE TABLE'],
        'yaml': ['---', ':', '- ', 'version:'],
        'json': ['{', '}', '":', '"'],
        'rust': ['fn ', 'let ', 'mut ', 'impl ', 'struct '],
        'go': ['package ', 'func ', 'import ', 'var ', 'const '],
        'java': ['public ', 'class ', 'void ', 'import ', 'System.out']
    }
    
    @staticmethod
    def process_markdown(text: str) -> str:
        """Convertit Markdown en HTML avec coloration syntaxique avancée"""
        if not text:
            return ""
        
        # Nettoyer et normaliser
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Traitement spécial pour les blocs de code
        processed_lines = []
        lines = text.split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Détecter les blocs de code ```lang
            code_match = re.match(r'^```(\w+)?\s*(.*?)$', line.strip())
            if code_match:
                lang = code_match.group(1) or ""
                code_info = code_match.group(2) or ""
                
                # Trouver la fin du bloc
                j = i + 1
                code_content = []
                while j < len(lines) and not lines[j].strip().startswith('```'):
                    code_content.append(lines[j])
                    j += 1
                
                if j < len(lines):
                    # Formater le bloc de code
                    formatted = MarkdownProcessor._format_code_block(
                        '\n'.join(code_content), 
                        lang,
                        code_info
                    )
                    processed_lines.append(formatted)
                    i = j + 1
                    continue
            
            # Détecter le code inline `code`
            line = re.sub(
                r'`([^`\n]+?)`',
                r'<code class="inline-code">\1</code>',
                line
            )
            
            processed_lines.append(line)
            i += 1
        
        # Rejoindre et traiter avec markdown
        processed_text = '\n'.join(processed_lines)
        
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
        
        html = markdown.markdown(processed_text, extensions=extensions)
        
        # Post-traitement pour améliorer l'affichage
        html = MarkdownProcessor._post_process_html(html)
        
        return html
    
    @staticmethod
    def _format_code_block(code: str, lang: str = "", info: str = "") -> str:
        """Formate un bloc de code avec détection automatique"""
        code = code.rstrip()
        
        # Détecter le langage si non spécifié
        if not lang:
            lang = MarkdownProcessor.detect_language_from_content(code)
        
        # Nettoyer le langage
        lang = lang.lower().strip()
        
        # Extraire les métadonnées du info
        metadata = {}
        if info:
            for part in info.split(','):
                if '=' in part:
                    key, value = part.split('=', 1)
                    metadata[key.strip()] = value.strip()
                else:
                    metadata['title'] = part.strip()
        
        # Classes CSS
        lang_class = f"language-{lang}" if lang else ""
        title_html = f' data-title="{metadata.get("title", "")}"' if 'title' in metadata else ""
        
        # Numérotation des lignes
        line_numbers = ""
        if 'linenums' in metadata or 'ln' in metadata:
            line_numbers = ' class="with-line-numbers"'
            code_lines = code.split('\n')
            line_nums = '\n'.join([f'<span class="line-number">{i+1}</span>' 
                                 for i in range(len(code_lines))])
            line_numbers_html = f'<div class="line-numbers">{line_nums}</div>'
            code = f'<div class="code-content">{code}</div>'
            code = f'<div class="code-container">{line_numbers_html}{code}</div>'
        
        # Highlight les lignes spécifiques
        highlighted_lines = ""
        if 'hl' in metadata:
            lines_to_highlight = []
            for part in metadata['hl'].split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    lines_to_highlight.extend(range(start, end + 1))
                else:
                    lines_to_highlight.append(int(part))
            
            code_lines = code.split('\n')
            highlighted = []
            for idx, line in enumerate(code_lines, 1):
                if idx in lines_to_highlight:
                    highlighted.append(f'<span class="highlight-line">{line}</span>')
                else:
                    highlighted.append(line)
            code = '\n'.join(highlighted)
        
        return f'''
        <div class="code-block-wrapper"{title_html}>
            <div class="code-header">
                <span class="language-label">{lang.upper() if lang else "TEXT"}</span>
                <button class="copy-btn" onclick="copyCode(this)">Copier</button>
            </div>
            <pre{line_numbers}><code class="{lang_class}">{code}</code></pre>
        </div>
        '''
    
    @staticmethod
    def detect_language_from_content(content: str) -> str:
        """Détecte le langage basé sur le contenu"""
        content_lower = content.lower()
        content_first_lines = '\n'.join(content.split('\n')[:10])
        
        # Vérifier chaque langage
        for lang, keywords in MarkdownProcessor.LANGUAGE_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    return lang
        
        # Détection spécifique Zenv
        if re.search(r'==>\s*', content):
            return 'zenv'
        if re.search(r'zncv\.\[\(', content):
            return 'zenv'
        if re.search(r'zen\[', content):
            return 'zenv'
        
        # Détection par extensions dans les commentaires
        ext_pattern = re.search(r'\.(py|js|java|go|rs|dockerfile|sql|html|css)$', content_first_lines, re.IGNORECASE)
        if ext_pattern:
            ext = ext_pattern.group(1).lower()
            ext_map = {
                'py': 'python',
                'js': 'javascript',
                'java': 'java',
                'go': 'go',
                'rs': 'rust',
                'dockerfile': 'docker',
                'sql': 'sql',
                'html': 'html',
                'css': 'css'
            }
            return ext_map.get(ext, 'text')
        
        return 'text'
    
    @staticmethod
    def _post_process_html(html: str) -> str:
        """Post-traitement HTML pour améliorer l'affichage"""
        # Ajouter des classes aux tableaux
        html = re.sub(r'<table>', r'<table class="table table-dark table-striped">', html)
        
        # Améliorer les blocs de citation
        html = re.sub(r'<blockquote>', r'<blockquote class="blockquote">', html)
        
        # Ajouter des ancres aux en-têtes
        def add_anchor(match):
            tag = match.group(1)
            content = match.group(2)
            anchor = re.sub(r'[^\w\s-]', '', content.lower())
            anchor = re.sub(r'[-\s]+', '-', anchor).strip('-')
            return f'<{tag} id="{anchor}">{content} <a href="#{anchor}" class="header-anchor">#</a></{tag}>'
        
        html = re.sub(r'<(h[2-6])>(.*?)</\1>', add_anchor, html)
        
        return html

class BadgeGenerator:
    """Générateur et gestionnaire de badges SVG"""
    
    COLORS = {
        'blue': '#007ec6',
        'green': '#4c1',
        'red': '#e05d44',
        'orange': '#fe7d37',
        'yellow': '#dfb317',
        'purple': '#9f5f9f',
        'gray': '#9f9f9f',
        'success': '#4c1',
        'warning': '#dfb317',
        'error': '#e05d44',
        'info': '#007ec6'
    }
    
    STYLES = {
        'flat': {'rx': '3'},
        'plastic': {'rx': '4', 'filter': 'url(#plastic)'},
        'flat-square': {'rx': '0'},
        'social': {'rx': '5', 'filter': 'url(#shadow)'}
    }
    
    @staticmethod
    def create_svg_badge(label: str, value: str, color: str = "blue", style: str = "flat") -> str:
        """Crée un badge SVG personnalisé"""
        # Couleurs
        label_color = BadgeGenerator.COLORS.get(color, BadgeGenerator.COLORS['blue'])
        value_color = BadgeGenerator._darken_color(label_color, 0.2)
        
        # Dimensions
        label_width = max(len(label) * 6 + 10, 30)
        value_width = max(len(value) * 6 + 10, 30)
        total_width = label_width + value_width
        height = 20
        
        # Style
        style_attrs = BadgeGenerator.STYLES.get(style, BadgeGenerator.STYLES['flat'])
        
        # SVG avec style
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
        <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" 
             width="{total_width}" height="{height}" role="img" aria-label="{label}: {value}">
            <title>{label}: {value}</title>
            
            <defs>
                <linearGradient id="labelGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="{label_color}" stop-opacity="0.9"/>
                    <stop offset="100%" stop-color="{BadgeGenerator._darken_color(label_color, 0.3)}" stop-opacity="0.9"/>
                </linearGradient>
                <linearGradient id="valueGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stop-color="{value_color}" stop-opacity="0.9"/>
                    <stop offset="100%" stop-color="{BadgeGenerator._darken_color(value_color, 0.3)}" stop-opacity="0.9"/>
                </linearGradient>
                <filter id="shadow" x="-0.1" y="-0.1" width="1.2" height="1.2">
                    <feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.3"/>
                </filter>
            </defs>
            
            <g>
                <!-- Partie label -->
                <rect width="{label_width}" height="{height}" fill="url(#labelGradient)" {BadgeGenerator._dict_to_attrs(style_attrs)}/>
                
                <!-- Partie value -->
                <rect x="{label_width}" width="{value_width}" height="{height}" fill="url(#valueGradient)" {BadgeGenerator._dict_to_attrs(style_attrs)}/>
                
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
    def create_dynamic_badge(package_name: str, metric: str, style: str = "flat") -> str:
        """Crée un badge dynamique basé sur les métriques du package"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Récupérer les stats du package
            cur.execute('''
                SELECT p.name, p.version, p.downloads_count, 
                       COUNT(r.id) as release_count,
                       p.created_at
                FROM packages p
                LEFT JOIN releases r ON p.id = r.package_id
                WHERE p.name = %s
                GROUP BY p.id
            ''', (package_name,))
            
            package = cur.fetchone()
            
            if not package:
                return BadgeGenerator.create_svg_badge(package_name, "Not Found", "red", style)
            
            # Déterminer la valeur basée sur la métrique
            metric_map = {
                'version': ('Version', package['version'], 'blue'),
                'downloads': ('Downloads', str(package['downloads_count']), 'green'),
                'releases': ('Releases', str(package['release_count']), 'orange'),
                'status': ('Status', 'Active', 'success'),
                'license': ('License', 'MIT', 'purple'),
                'python': ('Python', '>=3.6', 'yellow')
            }
            
            if metric in metric_map:
                label, value, color = metric_map[metric]
            else:
                # Métrique personnalisée
                label = metric.capitalize()
                value = "N/A"
                color = "gray"
            
            return BadgeGenerator.create_svg_badge(label, value, color, style)
            
        except Exception as e:
            print(f"Erreur création badge: {e}")
            return BadgeGenerator.create_svg_badge("Error", "Badge Error", "red", style)
        finally:
            cur.close()
            conn.close()
    
    @staticmethod
    def _darken_color(hex_color: str, factor: float = 0.2) -> str:
        """Assombrit une couleur hexadécimale"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    @staticmethod
    def _dict_to_attrs(attrs_dict: dict) -> str:
        """Convertit un dictionnaire en attributs HTML"""
        return ' '.join([f'{k}="{v}"' for k, v in attrs_dict.items()])
    
    @staticmethod
    def save_badge_svg(badge_name: str, svg_content: str) -> str:
        """Sauvegarde un badge SVG sur le disque"""
        badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
        
        with open(badge_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        
        return badge_path
    
    @staticmethod
    def get_badge_url(badge_name: str) -> str:
        """Retourne l'URL d'un badge"""
        return f"/static/badges/{badge_name}.svg"
    
    @staticmethod
    def generate_markdown_badge(badge_name: str, alt_text: str = None) -> str:
        """Génère le code Markdown pour un badge"""
        url = BadgeGenerator.get_badge_url(badge_name)
        alt = alt_text or badge_name.replace('-', ' ').title()
        
        return f'![{alt}]({url})'

# ============================================================================
# DÉCORATEURS D'AUTHENTIFICATION
# ============================================================================

def login_required(f):
    """Décorateur pour les routes nécessitant une authentification"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Vérifier la session
        if 'usr_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            flash('Veuillez vous connecter pour accéder à cette page', 'warning')
            return redirect(url_for('login'))
        
        # Vérifier le token JWT
        auth_header = request.headers.get('Authorization')
        token = None
        
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
        if request.usr_role != 'admin':
            if request.is_json:
                return jsonify({'error': 'Admin access required'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# ROUTES D'AUTHENTIFICATION (USRS)
# ============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Connexion usr"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute('''
                SELECT id, username, email, password, role 
                FROM usrs 
                WHERE username = %s OR email = %s
            ''', (username, username))
            
            usr = cur.fetchone()
            
            if usr and SecurityUtils.verify_password(password, usr['password']):
                # Mettre à jour last_login
                cur.execute('UPDATE usrs SET last_login = CURRENT_TIMESTAMP WHERE id = %s', (usr['id'],))
                
                # Générer les tokens
                tokens = SecurityUtils.generate_token(usr['id'], usr['role'])
                
                # Stocker en session
                session['usr_id'] = usr['id']
                session['username'] = usr['username']
                session['role'] = usr['role']
                session['access_token'] = tokens['access_token']
                
                conn.commit()
                
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
    """Inscription usr"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        # Validation
        if password != confirm:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html')
        
        if len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
            return render_template('register.html')
        
        # Hasher le mot de passe
        hashed_pw = SecurityUtils.hash_password(password)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
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
# ROUTES PRINCIPALES
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Packages récents
        cur.execute('''
            SELECT p.*, u.username as author_name,
                   COUNT(r.id) as release_count
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.is_private = FALSE
            GROUP BY p.id, u.id
            ORDER BY p.created_at DESC
            LIMIT 6
        ''')
        recent_packages = cur.fetchall()
        
        # Statistiques
        cur.execute('SELECT COUNT(*) as total_usrs FROM usrs')
        total_usrs = cur.fetchone()['total_usrs']
        
        cur.execute('SELECT COUNT(*) as total_packages FROM packages WHERE is_private = FALSE')
        total_packages = cur.fetchone()['total_packages']
        
        cur.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
        total_downloads = cur.fetchone()['total_downloads']
        
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
        
    except Exception as e:
        print(f"Erreur index: {e}")
        recent_packages = []
        popular_badges = []
        total_usrs = 0
        total_packages = 0
        total_downloads = 0
    finally:
        cur.close()
        conn.close()
    
    return render_template('index.html',
                         recent_packages=recent_packages,
                         popular_badges=popular_badges,
                         total_usrs=total_usrs,
                         total_packages=total_packages,
                         total_downloads=total_downloads)

@app.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord usr"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Infos usr
        cur.execute('SELECT username, email, role, created_at FROM usrs WHERE id = %s', 
                   (session['usr_id'],))
        usr = cur.fetchone()
        
        # Packages de l'usr
        cur.execute('''
            SELECT p.*, COUNT(r.id) as release_count
            FROM packages p
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.usr_id = %s
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            LIMIT 10
        ''', (session['usr_id'],))
        packages = cur.fetchall()
        
        # Statistiques
        cur.execute('''
            SELECT 
                COUNT(DISTINCT p.id) as total_packages,
                COUNT(r.id) as total_releases,
                COALESCE(SUM(r.download_count), 0) as total_downloads
            FROM packages p
            LEFT JOIN releases r ON p.id = r.package_id
            WHERE p.usr_id = %s
        ''', (session['usr_id'],))
        stats = cur.fetchone()
        
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
        
    except Exception as e:
        print(f"Erreur dashboard: {e}")
        usr = {}
        packages = []
        stats = {}
        usr_badges = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('dashboard.html',
                         usr=usr,
                         packages=packages,
                         stats=stats,
                         usr_badges=usr_badges)

# ============================================================================
# ROUTES PACKAGES
# ============================================================================

@app.route('/packages')
def list_packages():
    """Liste des packages"""
    page = int(request.args.get('page', 1))
    per_page = 20
    search = request.args.get('q', '')
    language = request.args.get('lang', '')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        query = '''
            SELECT p.*, u.username as author_name,
                   COUNT(r.id) as release_count,
                   COALESCE(SUM(r.download_count), 0) as total_downloads
            FROM packages p
            LEFT JOIN usrs u ON p.usr_id = u.id
            LEFT JOIN releases r ON p.id = r.package_id
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
        
        query += ' GROUP BY p.id, u.id ORDER BY p.updated_at DESC'
        
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
        total = cur.fetchone()['count']
        
        # Langages disponibles
        cur.execute('SELECT DISTINCT language FROM packages WHERE language IS NOT NULL ORDER BY language')
        languages = [row['language'] for row in cur.fetchall()]
        
    except Exception as e:
        print(f"Erreur list_packages: {e}")
        packages = []
        total = 0
        languages = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('packages.html',
                         packages=packages,
                         page=page,
                         per_page=per_page,
                         total=total,
                         total_pages=(total + per_page - 1) // per_page,
                         search=search,
                         language=language,
                         languages=languages)

@app.route('/package/<package_name>')
def package_detail(package_name):
    """Détails d'un package"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
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
        
    except Exception as e:
        print(f"Erreur package_detail: {e}")
        flash('Erreur lors du chargement du package', 'danger')
        return redirect(url_for('list_packages'))
    finally:
        cur.close()
        conn.close()
    
    return render_template('package_detail.html',
                         package=package,
                         releases=releases,
                         badges=badges,
                         readme_html=readme_html)

# ============================================================================
# ROUTES BADGES
# ============================================================================

@app.route('/badges')
def list_badges():
    """Liste des badges"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT b.*, u.username as created_by_name
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            WHERE b.is_active = TRUE
            ORDER BY b.usage_count DESC, b.name
        ''')
        
        badges = cur.fetchall()
        
    except Exception as e:
        print(f"Erreur list_badges: {e}")
        badges = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('badges.html', badges=badges)

@app.route('/badge/<badge_name>')
def badge_detail(badge_name):
    """Détails d'un badge"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
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
        
        # Générer le code Markdown
        markdown_code = BadgeGenerator.generate_markdown_badge(badge_name, f"{badge['label']}: {badge['value']}")
        
    except Exception as e:
        print(f"Erreur badge_detail: {e}")
        flash('Erreur lors du chargement du badge', 'danger')
        return redirect(url_for('list_badges'))
    finally:
        cur.close()
        conn.close()
    
    return render_template('badge_detail.html',
                         badge=badge,
                         packages=packages,
                         markdown_code=markdown_code)

@app.route('/badge/generate', methods=['GET', 'POST'])
@login_required
def generate_badge():
    """Générer un nouveau badge"""
    if request.method == 'POST':
        name = request.form.get('name')
        label = request.form.get('label')
        value = request.form.get('value')
        color = request.form.get('color', 'blue')
        style = request.form.get('style', 'flat')
        
        # Validation
        if not name or not label or not value:
            flash('Tous les champs sont requis', 'danger')
            return render_template('generate_badge.html')
        
        # Générer le SVG
        svg_content = BadgeGenerator.create_svg_badge(label, value, color, style)
        
        # Sauvegarder sur disque
        BadgeGenerator.save_badge_svg(name, svg_content)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
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
    
    return render_template('generate_badge.html')

@app.route('/badge/svg/<badge_name>')
def serve_badge_svg(badge_name):
    """Servir un badge SVG"""
    badge_path = os.path.join(app.config['SVG_DIR'], f"{badge_name}.svg")
    
    if not os.path.exists(badge_path):
        # Générer un badge par défaut
        svg_content = BadgeGenerator.create_svg_badge("Not Found", "404", "red")
        return Response(svg_content, mimetype='image/svg+xml')
    
    return send_file(badge_path, mimetype='image/svg+xml')

@app.route('/badge/dynamic/<package_name>/<metric>')
def dynamic_badge(package_name: str, metric: str):
    """Badge dynamique pour un package"""
    style = request.args.get('style', 'flat')
    
    svg_content = BadgeGenerator.create_dynamic_badge(package_name, metric, style)
    
    # Mettre à jour le compteur d'utilisation
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute('''
            UPDATE badges 
            SET usage_count = usage_count + 1 
            WHERE name = %s
        ''', (f"{package_name}-{metric}",))
        conn.commit()
    except:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    
    return Response(svg_content, mimetype='image/svg+xml')

# ============================================================================
# ROUTES ADMIN
# ============================================================================

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Tableau de bord admin"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Statistiques
        cur.execute('SELECT COUNT(*) as total_usrs FROM usrs')
        total_usrs = cur.fetchone()['total_usrs']
        
        cur.execute('SELECT COUNT(*) as total_packages FROM packages')
        total_packages = cur.fetchone()['total_packages']
        
        cur.execute('SELECT COUNT(*) as total_badges FROM badges')
        total_badges = cur.fetchone()['total_badges']
        
        cur.execute('SELECT COALESCE(SUM(downloads_count), 0) as total_downloads FROM packages')
        total_downloads = cur.fetchone()['total_downloads']
        
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
        
    except Exception as e:
        print(f"Erreur admin_dashboard: {e}")
        total_usrs = total_packages = total_badges = total_downloads = 0
        recent_usrs = []
        recent_packages = []
        recent_badges = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('admin/dashboard.html',
                         total_usrs=total_usrs,
                         total_packages=total_packages,
                         total_badges=total_badges,
                         total_downloads=total_downloads,
                         recent_usrs=recent_usrs,
                         recent_packages=recent_packages,
                         recent_badges=recent_badges)

@app.route('/admin/badges', methods=['GET', 'POST'])
@admin_required
def admin_manage_badges():
    """Gestion des badges par l'admin"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if request.method == 'POST':
        action = request.form.get('action')
        badge_id = request.form.get('badge_id')
        
        if action == 'edit' and badge_id:
            # Édition de badge
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
        
        elif action == 'delete' and badge_id:
            # Suppression de badge
            try:
                cur.execute('DELETE FROM badges WHERE id = %s', (badge_id,))
                conn.commit()
                flash('Badge supprimé avec succès', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Erreur: {str(e)}', 'danger')
    
    # Récupérer tous les badges
    try:
        cur.execute('''
            SELECT b.*, u.username as created_by_name,
                   COUNT(ba.id) as assignment_count
            FROM badges b
            LEFT JOIN usrs u ON b.created_by = u.id
            LEFT JOIN badge_assignments ba ON b.id = ba.badge_id
            GROUP BY b.id, u.id
            ORDER BY b.name
        ''')
        
        badges = cur.fetchall()
        
    except Exception as e:
        print(f"Erreur admin_manage_badges: {e}")
        badges = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('admin/manage_badges.html', badges=badges)

@app.route('/admin/badge/editor/<badge_id>')
@admin_required
def admin_badge_editor(badge_id):
    """Éditeur de badge pour admin"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('SELECT * FROM badges WHERE id = %s', (badge_id,))
        badge = cur.fetchone()
        
        if not badge:
            flash('Badge non trouvé', 'danger')
            return redirect(url_for('admin_manage_badges'))
        
    except Exception as e:
        print(f"Erreur admin_badge_editor: {e}")
        badge = None
    finally:
        cur.close()
        conn.close()
    
    if not badge:
        return redirect(url_for('admin_manage_badges'))
    
    return render_template('admin/badge_editor.html', badge=badge)

# ============================================================================
# ROUTES API
# ============================================================================

@app.route('/api/v1/packages')
def api_list_packages():
    """API: Liste des packages"""
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 20)), 100)
    search = request.args.get('q', '')
    language = request.args.get('lang', '')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
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
        total = cur.fetchone()['count']
        
        return jsonify({
            'packages': packages,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/v1/badges')
def api_list_badges():
    """API: Liste des badges"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute('''
            SELECT name, label, value, color, usage_count
            FROM badges
            WHERE is_active = TRUE
            ORDER BY name
        ''')
        
        badges = cur.fetchall()
        
        return jsonify({'badges': badges})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# ============================================================================
# INITIALISATION
# ============================================================================

@app.before_first_request
def initialize_app():
    """Initialise l'application"""
    try:
        init_postgresql()
        print("✅ Application initialisée avec succès")
    except Exception as e:
        print(f"❌ Erreur initialisation: {e}")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Initialiser
    initialize_app()
    
    # Démarrer
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    )
