#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zarch Package Registry v5.2 - Production Edition
Sécurité renforcée, API versionnée, Cookies sécurisés
Stockage GitHub préservé
"""

import os
import json
import base64
import secrets
import bcrypt
import tempfile
import shutil
import uuid
import requests
import tarfile
import hashlib
import hmac
import logging
import logging.handlers
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

# Flask et extensions
from flask import Flask, request, jsonify, g, render_template, make_response, session, redirect, flash, abort
from flask_cors import CORS

# Sécurité avancée
import ssl
import cryptography
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from itsdangerous import URLSafeTimedSerializer  # Uniquement celui-ci
import jwt  # Pour les JWT
import bleach
import markupsafe
from markupsafe import escape
import pydantic
from pydantic import BaseModel, validator, ValidationError
import paramiko
import OpenSSL

# Logging structuré
from pythonjsonlogger import jsonlogger

# Variables d'environnement
from dotenv import load_dotenv

# Markdown
import markdown
from markdown.extensions import extra, codehilite, toc, tables


# ============================================================================
# CHARGEMENT DES VARIABLES D'ENVIRONNEMENT
# ============================================================================

load_dotenv()

# ============================================================================
# CONFIGURATION DE SÉCURITÉ
# ============================================================================

class SecurityConfig:
    # Clés de chiffrement
    FERNET_KEY = os.environ.get('FERNET_KEY', Fernet.generate_key().decode())
    JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
    APP_SECRET = os.environ.get('APP_SECRET', secrets.token_hex(32))
    COOKIE_SECRET = os.environ.get('COOKIE_SECRET', secrets.token_hex(32))
    
    # GitHub (inchangé)
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "")
    GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/gsql-badge")
    GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package-data")
    
    # Paramètres de sécurité
    SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 360020312))  # 1 heure
    TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 6048008888))  # 7 jours
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB
    RATE_LIMIT = int(os.environ.get('RATE_LIMIT', 2100))  # Requêtes par minute
    COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'False').lower() == 'true'
    COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'Lax')

# ============================================================================
# INITIALISATION FLASK
# ============================================================================

app = Flask(__name__, template_folder='templates', static_folder='static')

# Configuration de l'application
app.config.update(
    SECRET_KEY=SecurityConfig.APP_SECRET,
    MAX_CONTENT_LENGTH=SecurityConfig.MAX_CONTENT_LENGTH,
    JSON_SORT_KEYS=True,
    SESSION_TYPE='filesystem',
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=SecurityConfig.SESSION_TIMEOUT),
    SESSION_COOKIE_SECURE=SecurityConfig.COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=SecurityConfig.COOKIE_SAMESITE,
    SESSION_COOKIE_NAME='zarch_session'
)

# CORS configuration
CORS(app, resources={
    r"/api/*": {"origins": "*"},
    r"/v5.2/*": {"origins": "*"}
})

# Initialisation du chiffreur Fernet
fernet = Fernet(SecurityConfig.FERNET_KEY.encode())

# Plus besoin de token_serializer, on utilise PyJWT directement
# La ligne suivante est à SUPPRIMER :
# token_serializer = TimedJSONWebSignatureSerializer(SecurityConfig.JWT_SECRET, expires_in=3600)

# ============================================================================
# CONFIGURATION DES LOGS
# ============================================================================

log_handler = logging.handlers.RotatingFileHandler(
    'zarch_security.log', maxBytes=10485760, backupCount=10
)
log_formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(funcName)s %(lineno)d'
)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

# ============================================================================
# MODÈLES PYDANTIC (Validation des données)
# ============================================================================

class UserLogin(BaseModel):
    username: str
    password: str
    
    @validator('username')
    def validate_username(cls, v):
        if not v or len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        if not v.isalnum() and '_' not in v:
            raise ValueError('Username can only contain letters, numbers and underscores')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    
    @validator('username')
    def validate_username(cls, v):
        if not v or len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        return v
    
    @validator('email')
    def validate_email(cls, v):
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one number')
        return v

class PackageUpload(BaseModel):
    name: str
    version: str
    scope: str = 'public'
    release: str = 'r0'
    arch: str = 'x86_64'
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v) < 1:
            raise ValueError('Package name is required')
        return v
    
    @validator('version')
    def validate_version(cls, v):
        if not v:
            raise ValueError('Version is required')
        return v

# ============================================================================
# GESTION DES COOKIES SÉCURISÉS
# ============================================================================

class CookieManager:
    @staticmethod
    def set_secure_cookie(response, name, value, max_age=3600):
        """Définit un cookie sécurisé avec chiffrement"""
        encrypted = fernet.encrypt(value.encode()).decode()
        response.set_cookie(
            name,
            encrypted,
            max_age=max_age,
            secure=SecurityConfig.COOKIE_SECURE,
            httponly=True,
            samesite=SecurityConfig.COOKIE_SAMESITE,
            path='/'
        )
        return response
    
    @staticmethod
    def get_secure_cookie(request, name):
        """Récupère et déchiffre un cookie"""
        encrypted = request.cookies.get(name)
        if not encrypted:
            return None
        try:
            decrypted = fernet.decrypt(encrypted.encode()).decode()
            return decrypted
        except Exception as e:
            app.logger.warning(f"Failed to decrypt cookie {name}: {e}")
            return None
    
    @staticmethod
    def delete_secure_cookie(response, name):
        """Supprime un cookie"""
        response.set_cookie(name, '', expires=0, path='/')
        return response

# ============================================================================
# CACHE & PERFORMANCE
# ============================================================================

class CacheManager:
    _cache = {}
    _ttl = 60  # Cache court (1 min)
    
    @staticmethod
    def get(key):
        data = CacheManager._cache.get(key)
        if data:
            value, timestamp = data
            if datetime.now().timestamp() - timestamp < CacheManager._ttl:
                return value
            else:
                del CacheManager._cache[key]
        return None
    
    @staticmethod
    def set(key, value):
        CacheManager._cache[key] = (value, datetime.now().timestamp())
    
    @staticmethod
    def invalidate(pattern):
        keys = [k for k in CacheManager._cache.keys() if pattern in k]
        for k in keys:
            del CacheManager._cache[k]

# ============================================================================
# GITHUB MANAGER (INCHANGÉ - PRÉSERVÉ)
# ============================================================================

class GitHubManager:
    @staticmethod
    def get_headers():
        return {
            'Authorization': f'token {SecurityConfig.GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Zarch-Server/5.2'
        }
    
    @staticmethod
    def get_api_url(path=""):
        return f'https://api.github.com/repos/{SecurityConfig.GITHUB_REPO}/contents/{path.lstrip("/")}'
    
    @staticmethod
    def read_from_github(path, default=None, use_cache=True, binary=False):
        cache_key = f"github:{path}:{binary}"
        if use_cache and not binary:
            cached = CacheManager.get(cache_key)
            if cached is not None: return cached
        
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3.raw'
            
            resp = requests.get(
                GitHubManager.get_api_url(path), 
                headers=headers, 
                params={'ref': SecurityConfig.GITHUB_BRANCH},
                timeout=45,
                stream=True 
            )
            
            if resp.status_code == 200:
                if binary:
                    return resp.content 
                
                text_content = resp.text
                try:
                    result = json.loads(text_content)
                except json.JSONDecodeError:
                    result = text_content
                
                if use_cache:
                    CacheManager.set(cache_key, result)
                return result
            
            if resp.status_code == 404:
                return default
                
            app.logger.warning(f"GitHub Error {resp.status_code} reading {path}")
            return default

        except Exception as e:
            app.logger.error(f"Read exception {path}: {e}")
            return default
    
    @staticmethod
    def save_to_github(path, content, message="Update"):
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3+json'
            
            sha = None
            check_resp = requests.get(
                GitHubManager.get_api_url(path), 
                headers=headers, 
                params={'ref': SecurityConfig.GITHUB_BRANCH}
            )
            if check_resp.status_code == 200:
                sha = check_resp.json().get('sha')
            
            if isinstance(content, (dict, list)):
                content_bytes = json.dumps(content, indent=2).encode('utf-8')
            elif isinstance(content, str):
                content_bytes = content.encode('utf-8')
            else:
                content_bytes = content
            
            data = {
                'message': f'[ZARCH] {message}',
                'content': base64.b64encode(content_bytes).decode('utf-8'),
                'branch': SecurityConfig.GITHUB_BRANCH
            }
            if sha: data['sha'] = sha
            
            r = requests.put(GitHubManager.get_api_url(path), headers=headers, json=data)
            
            if r.status_code in [200, 201]:
                CacheManager.invalidate(f"github:{path}")
                return True
            
            app.logger.error(f"Save Error {r.status_code}: {r.text}")
            return False
        except Exception as e:
            app.logger.error(f"Save Exception {path}: {e}")
            return False
# ============================================================================
# SÉCURITÉ & AUTH AVANCÉE (VERSION CORRIGÉE AVEC PyJWT)
# ============================================================================

class SecurityUtils:
    @staticmethod
    def hash_password(password):
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    @staticmethod
    def check_password(password, hashed):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except:
            return False
    
    @staticmethod
    def generate_token(username, role="user"):
        """Génère un token JWT signé avec PyJWT"""
        payload = {
            'username': username,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(seconds=SecurityConfig.TOKEN_EXPIRY)
        }
        token = jwt.encode(payload, SecurityConfig.JWT_SECRET, algorithm='HS256')
        
        # Sauvegarde dans GitHub
        tokens_db = GitHubManager.read_from_github('tokens/tokens.json', {'tokens': []})
        if isinstance(tokens_db, dict) and 'tokens' in tokens_db:
            tokens_db['tokens'] = [t for t in tokens_db['tokens'] if t['username'] != username]
            tokens_db['tokens'].append({
                'token': token,
                'username': username,
                'role': role,
                'created_at': datetime.now().isoformat(),
                'active': True
            })
            GitHubManager.save_to_github('tokens/tokens.json', tokens_db, f"Token {username}")
        
        return token
    
    @staticmethod
    def validate_token(token):
        """Valide un token JWT avec PyJWT"""
        try:
            payload = jwt.decode(token, SecurityConfig.JWT_SECRET, algorithms=['HS256'])
            username = payload.get('username')
            
            # Vérification supplémentaire dans GitHub
            tokens_db = GitHubManager.read_from_github('tokens/tokens.json', {'tokens': []})
            if isinstance(tokens_db, dict):
                for t in tokens_db.get('tokens', []):
                    if t.get('token') == token and t.get('active', True):
                        return {
                            'username': username,
                            'role': t.get('role'),
                            'token': token
                        }
            return None
        except jwt.ExpiredSignatureError:
            app.logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            app.logger.warning(f"Invalid token: {e}")
            return None
    
    @staticmethod
    def sanitize_html(content):
        """Nettoie le HTML pour éviter les XSS"""
        return bleach.clean(
            content,
            tags=['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a', 'img'],
            attributes={'a': ['href', 'title'], 'img': ['src', 'alt']},
            strip=True
        )
    
    @staticmethod
    def escape_text(text):
        """Échappe le texte pour éviter l'injection"""
        return escape(str(text))

# ============================================================================
# MARKDOWN RENDERER POUR README
# ============================================================================

class MarkdownRenderer:
    @staticmethod
    def render(text):
        """Convertit le markdown en HTML sécurisé"""
        if not text:
            return "<p>No documentation available.</p>"
        
        # Extensions markdown
        extensions = [
            'extra',
            'codehilite',
            'toc',
            'tables',
            'fenced_code',
            'sane_lists'
        ]
        
        # Conversion
        html = markdown.markdown(text, extensions=extensions)
        
        # Nettoyage sécurité
        html = SecurityUtils.sanitize_html(html)
        
        # Ajout du style GitHub
        return f'''
        <div class="markdown-body">
            {html}
        </div>
        '''
    
    @staticmethod
    def extract_from_tar(tar_path):
        """Extrait le README d'un fichier .tar.bool"""
        try:
            with tarfile.open(tar_path, 'r:*') as tar:
                # Chercher README.md ou README
                for member in tar.getmembers():
                    name = member.name.lower()
                    if 'readme' in name and (name.endswith('.md') or '.txt' in name or name == 'readme'):
                        content = tar.extractfile(member).read().decode('utf-8', errors='ignore')
                        return content
                    
                    # Chercher dans doc/docs
                    if 'doc' in name or 'docs' in name:
                        try:
                            f = tar.extractfile(member)
                            if f:
                                content = f.read().decode('utf-8', errors='ignore')
                                if '# ' in content or 'README' in content:
                                    return content
                        except:
                            pass
        except Exception as e:
            app.logger.error(f"Error extracting README: {e}")
        
        return None

# ============================================================================
# MIDDLEWARE DE SÉCURITÉ
# ============================================================================

@app.before_request
def before_request():
    """Middleware exécuté avant chaque requête"""
    # Audit logging
    app.logger.info('Request', extra={
        'method': request.method,
        'path': request.path,
        'ip': request.remote_addr,
        'user_agent': request.user_agent.string
    })
    
    # Rate limiting simple
    g.request_time = datetime.now()
    
    # Vérification du token dans les cookies
    if not session.get('user'):
        token = CookieManager.get_secure_cookie(request, 'zarch_token')
        if token:
            user = SecurityUtils.validate_token(token)
            if user:
                session['user'] = user

@app.after_request
def after_request(response):
    """Middleware exécuté après chaque requête"""
    # Ajout des headers de sécurité
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self' https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:;"
    
    # Audit logging
    app.logger.info('Response', extra={
        'status': response.status_code,
        'duration': (datetime.now() - g.request_time).total_seconds()
    })
    
    return response

# ============================================================================
# DÉCORATEURS DE SÉCURITÉ
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Vérifier dans headers
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split(" ")
            if len(parts) > 1:
                token = parts[1]
        
        # Vérifier dans cookies
        if not token:
            token = CookieManager.get_secure_cookie(request, 'zarch_token')
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        user = SecurityUtils.validate_token(token)
        if not user:
            return jsonify({'error': 'Invalid token'}), 401
        
        g.user = user
        return f(*args, **kwargs)
    return decorated

def rate_limit(limit=SecurityConfig.RATE_LIMIT, per=60):
    """Décorateur de rate limiting"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Implémentation simplifiée
            return f(*args, **kwargs)
        return decorated
    return decorator

# ============================================================================
# ROUTES API VERSIONNÉES (/v5.2/)
# ============================================================================

@app.route('/v5.2/auth/login', methods=['POST'])
@rate_limit()
def api_v52_login():
    """Login avec validation Pydantic"""
    try:
        data = request.get_json()
        validated = UserLogin(**data)
        
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        user = next((u for u in db.get('users', []) if u['username'] == validated.username), None)
        
        valid = False
        if user:
            if SecurityUtils.check_password(validated.password, user['password']):
                valid = True
        
        if valid:
            token = SecurityUtils.generate_token(validated.username, user.get('role', 'user'))
            
            # Session
            session['user'] = user
            session['token'] = token
            session.permanent = True
            
            # Cookie sécurisé
            response = jsonify({
                'success': True,
                'token': token,
                'user': {
                    'username': user['username'],
                    'role': user.get('role', 'user'),
                    'created_at': user.get('created_at')
                }
            })
            
            CookieManager.set_secure_cookie(response, 'zarch_token', token, SecurityConfig.TOKEN_EXPIRY)
            
            return response
        
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/v5.2/auth/register', methods=['POST'])
@rate_limit()
def api_v52_register():
    """Register avec validation Pydantic"""
    try:
        data = request.get_json()
        validated = UserRegister(**data)
        
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        if any(u['username'] == validated.username for u in db.get('users', [])):
            return jsonify({'error': 'User already exists'}), 400
        
        hashed = SecurityUtils.hash_password(validated.password)
        new_user = {
            'id': str(uuid.uuid4()),
            'username': validated.username,
            'email': validated.email,
            'password': hashed,
            'role': 'user',
            'created_at': datetime.now().isoformat()
        }
        
        db['users'].append(new_user)
        if GitHubManager.save_to_github('database/users.json', db, f"Reg {validated.username}"):
            token = SecurityUtils.generate_token(validated.username)
            
            # Session
            session['user'] = new_user
            session['token'] = token
            session.permanent = True
            
            # Cookie sécurisé
            response = jsonify({
                'success': True,
                'token': token,
                'user': {
                    'username': validated.username,
                    'role': 'user',
                    'created_at': new_user['created_at']
                }
            })
            
            CookieManager.set_secure_cookie(response, 'zarch_token', token, SecurityConfig.TOKEN_EXPIRY)
            
            return response
            
        return jsonify({'error': 'Save failed'}), 500
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/v5.2/package/upload/<scope>/<name>', methods=['POST'])
@token_required
@rate_limit()
def api_v52_upload_package(scope, name):
    """Upload de package avec validation"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file'}), 400
        
        file = request.files['file']
        version = request.form.get('version', '1.0.0')
        release = request.form.get('release', 'r0')
        arch = request.form.get('arch', 'x86_64')
        
        # Validation
        validated = PackageUpload(
            name=name,
            version=version,
            scope=scope,
            release=release,
            arch=arch
        )
        
        if not file.filename.endswith('.tar.bool'):
            return jsonify({'error': 'Invalid file type, must be .tar.bool'}), 400
        
        temp_dir = tempfile.mkdtemp()
        tar_path = os.path.join(temp_dir, file.filename)
        file.save(tar_path)
        
        try:
            with open(tar_path, 'rb') as f:
                file_content = f.read()
            
            sha256 = hashlib.sha256(file_content).hexdigest()
            
            filename = f"{name}-{version}-{release}-{arch}.tar.bool"
            pkg_path = f"packages/{scope}/{name}/{filename}"
            
            if not GitHubManager.save_to_github(pkg_path, file_content, f"Pkg {name} v{version}"):
                raise Exception("Binary upload failed")
            
            db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
            
            db['packages'] = [p for p in db.get('packages', []) 
                             if not (p['name'] == name and p['version'] == version)]
            
            entry = {
                'name': name,
                'scope': scope,
                'version': version,
                'release': release,
                'arch': arch,
                'author': g.user['username'],
                'sha256': sha256,
                'size': len(file_content),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'downloads': 0
            }
            db['packages'].append(entry)
            GitHubManager.save_to_github('database/zenv_hub.json', db, f"Index {name}")
            
            return jsonify({'success': True, 'package': entry})
            
        except Exception as e:
            app.logger.error(f"Upload error: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            shutil.rmtree(temp_dir)
            
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/v5.2/package/search', methods=['GET'])
@rate_limit()
def api_v52_search():
    """Recherche de packages"""
    q = request.args.get('q', '').lower()
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    
    results = []
    if isinstance(db, dict) and 'packages' in db:
        for p in db['packages']:
            if q in p['name'].lower() or q in p.get('description', '').lower():
                # Sanitize pour éviter les XSS
                safe_p = {
                    'name': SecurityUtils.escape_text(p['name']),
                    'version': SecurityUtils.escape_text(p['version']),
                    'author': SecurityUtils.escape_text(p['author']),
                    'downloads': p['downloads'],
                    'scope': p['scope']
                }
                results.append(safe_p)
    
    return jsonify({'results': results})

@app.route('/v5.2/package/<name>')
@rate_limit()
def api_v52_package_detail(name):
    """Détail d'un package avec README"""
    version = request.args.get('version')
    
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    if not isinstance(db, dict):
        db = {'packages': []}
    
    packages = db.get('packages', [])
    package = None
    
    for p in packages:
        if p['name'] == name:
            if version is None or p['version'] == version:
                package = p
                break
    
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    # Chercher le README
    readme = None
    filename = f"{name}-{package['version']}-{package.get('release', 'r0')}-{package.get('arch', 'x86_64')}.tar.bool"
    pkg_path = f"packages/{package['scope']}/{name}/{filename}"
    
    content = GitHubManager.read_from_github(pkg_path, default=None, binary=True)
    if content:
        # Sauvegarder temporairement pour extraction
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, filename)
        with open(temp_path, 'wb') as f:
            f.write(content)
        
        readme_text = MarkdownRenderer.extract_from_tar(temp_path)
        if readme_text:
            readme = MarkdownRenderer.render(readme_text)
        
        shutil.rmtree(temp_dir)
    
    # Package sécurisé
    safe_package = {
        'name': SecurityUtils.escape_text(package['name']),
        'version': SecurityUtils.escape_text(package['version']),
        'release': SecurityUtils.escape_text(package.get('release', 'r0')),
        'arch': SecurityUtils.escape_text(package.get('arch', 'x86_64')),
        'scope': package['scope'],
        'author': SecurityUtils.escape_text(package['author']),
        'sha256': package['sha256'],
        'size': package['size'],
        'downloads': package['downloads'],
        'created_at': package['created_at']
    }
    
    return jsonify({
        'package': safe_package,
        'readme': readme
    })

# ============================================================================
# ROUTES WEB (Pages)
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    
    if not isinstance(db, dict):
        db = {'packages': []}
    
    pkgs = db.get('packages', [])
    
    total_packages = len(pkgs)
    total_downloads = sum(p.get('downloads', 0) for p in pkgs)
    total_authors = len(set(p.get('author') for p in pkgs if p.get('author')))
    
    public_packages = [p for p in pkgs if p.get('scope') == 'public']
    public_packages.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    recent_packages = public_packages[:6]
    
    return render_template('index.html',
                         total_packages=total_packages,
                         total_downloads=total_downloads,
                         total_authors=total_authors,
                         packages=recent_packages,
                         now=datetime.now())

@app.route('/packages')
def packages_page():
    """Page de liste des packages"""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    query = request.args.get('q', '').lower()
    sort = request.args.get('sort', 'recent')
    scope_filter = request.args.get('scope', 'all')
    
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    
    if not isinstance(db, dict):
        db = {'packages': []}
    
    packages = db.get('packages', [])
    
    if scope_filter != 'all':
        packages = [p for p in packages if p.get('scope') == scope_filter]
    
    if query:
        packages = [p for p in packages if query in p.get('name', '').lower() 
                   or query in p.get('description', '').lower()]
    
    if sort == 'downloads':
        packages.sort(key=lambda x: x.get('downloads', 0), reverse=True)
    elif sort == 'name':
        packages.sort(key=lambda x: x.get('name', '').lower())
    elif sort == 'name_desc':
        packages.sort(key=lambda x: x.get('name', '').lower(), reverse=True)
    else:
        packages.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    total_packages = len(packages)
    total_pages = (total_packages + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_packages = packages[start:end]
    
    total_downloads = sum(p.get('downloads', 0) for p in packages)
    total_authors = len(set(p.get('author') for p in packages if p.get('author')))
    
    return render_template('packages.html',
                         packages=paginated_packages,
                         total_packages=total_packages,
                         total_downloads=total_downloads,
                         total_authors=total_authors,
                         total_pages=total_pages,
                         page=page,
                         per_page=per_page,
                         query=query,
                         sort=sort,
                         scope=scope_filter,
                         now=datetime.now())

@app.route('/package/<name>')
def package_detail_page(name):
    """Page de détail d'un package avec README"""
    version = request.args.get('version')
    
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    if not isinstance(db, dict):
        db = {'packages': []}
    
    packages = db.get('packages', [])
    package = None
    
    for p in packages:
        if p['name'] == name:
            if version is None or p['version'] == version:
                package = p
                break
    
    if not package:
        abort(404, description="Package not found")
    
    # Chercher le README
    readme_html = None
    filename = f"{name}-{package['version']}-{package.get('release', 'r0')}-{package.get('arch', 'x86_64')}.tar.bool"
    pkg_path = f"packages/{package['scope']}/{name}/{filename}"
    
    content = GitHubManager.read_from_github(pkg_path, default=None, binary=True)
    if content:
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, filename)
        with open(temp_path, 'wb') as f:
            f.write(content)
        
        readme_text = MarkdownRenderer.extract_from_tar(temp_path)
        if readme_text:
            readme_html = MarkdownRenderer.render(readme_text)
        
        shutil.rmtree(temp_dir)
    
    return render_template('package.html',
                         package=package,
                         readme_html=readme_html)

@app.route('/docs')
def docs_page():
    """Page de documentation"""
    return render_template('docs.html')

@app.route('/upload')
def upload_page():
    """Page d'upload"""
    user = session.get('user')
    if not user:
        flash('Please login to upload packages', 'info')
        return redirect('/login')
    return render_template('upload.html', user=user)

@app.route('/dashboard')
def dashboard_page():
    """Dashboard utilisateur avec statistiques réelles"""
    user = session.get('user')
    if not user:
        flash('Please login to access the dashboard', 'info')
        return redirect('/login')
    
    try:
        # Récupérer la base de données des packages
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        if not isinstance(db, dict):
            db = {'packages': []}
        
        # Filtrer les packages de l'utilisateur
        username = user.get('username')
        user_packages = [p for p in db.get('packages', []) if p.get('author') == username]
        
        # Calculer les statistiques
        total_packages = len(user_packages)
        total_downloads = sum(p.get('downloads', 0) for p in user_packages)
        
        # Date d'inscription (à adapter selon ta structure)
        member_since = user.get('created_at', '2026')[:10] if user.get('created_at') else '2026'
        
        # Statistiques pour l'affichage
        stats = {
            'packages': total_packages,
            'downloads': total_downloads,
            'member_since': member_since
        }
        
        # Données pour les graphiques (exemple)
        chart_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
        chart_data = [10, 20, 15, 25, 30, 35]  # À remplacer par des données réelles
        
        popular_labels = ['apkm', 'other', 'test']
        popular_data = [60, 25, 15]
        
        # Vérifier si l'utilisateur est admin
        is_admin = username in ['admin', 'gopu-inc', 'mauricio']
        
        return render_template('dashboard.html',
                             user=user,
                             user_packages=user_packages,
                             stats=stats,
                             chart_labels=chart_labels,
                             chart_data=chart_data,
                             popular_labels=popular_labels,
                             popular_data=popular_data,
                             is_admin=is_admin,
                             now=datetime.now())
    
    except Exception as e:
        app.logger.error(f"Dashboard error: {e}")
        flash('Error loading dashboard', 'error')
        return render_template('dashboard.html',
                             user=user,
                             user_packages=[],
                             stats={'packages': 0, 'downloads': 0, 'member_since': '2026'},
                             chart_labels=['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                             chart_data=[0,0,0,0,0,0],
                             popular_labels=['apkm', 'other', 'test'],
                             popular_data=[0,0,0],
                             is_admin=False,
                             now=datetime.now())

@app.route('/login')
def login_page():
    """Page de connexion"""
    if session.get('user'):
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/register')
def register_page():
    """Page d'inscription"""
    if session.get('user'):
        return redirect('/dashboard')
    return render_template('register.html')

@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    response = make_response(redirect('/'))
    CookieManager.delete_secure_cookie(response, 'zarch_token')
    flash('You have been logged out successfully', 'success')
    return response

@app.route('/stats')
def stats_page():
    """Page de statistiques"""
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    if not isinstance(db, dict):
        db = {'packages': []}
    
    packages = db.get('packages', [])
    
    stats = {
        'total_packages': len(packages),
        'total_downloads': sum(p.get('downloads', 0) for p in packages),
        'public_packages': len([p for p in packages if p.get('scope') == 'public']),
        'private_packages': len([p for p in packages if p.get('scope') == 'private']),
        'total_authors': len(set(p.get('author') for p in packages if p.get('author')))
    }
    
    return render_template('stats.html', stats=stats)

@app.route('/status')
def status_page():
    """Page de statut"""
    return render_template('status.html')

@app.route('/privacy')
def privacy_page():
    """Page de confidentialité"""
    return render_template('privacy.html')

@app.route('/terms')
def terms_page():
    """Page des conditions"""
    return render_template('terms.html')

@app.route('/api/docs')
def api_docs_page():
    """Documentation API"""
    return render_template('api_docs.html')

@app.route('/cookies')
def cookies_page():
    """Page d'information sur les cookies"""
    return render_template('cookies.html')



@app.route('/base')
def base_page():
    """Page d'information sur les base"""
    return render_template('base.html')

# ============================================================================
# ROUTES COMMUNAUTÉ
# ============================================================================

@app.route('/community')
def edit_community_page():
    """Page d'édition de la communauté (admin seulement)"""
    user = session.get('user')
    
    # Vérifier si l'utilisateur est admin
    is_admin = user and (user.get('username') in ['admin', 'gopu-inc', 'mauricio', 'Mauricio-100'] or user.get('role') == 'admin')
    
    if not is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect('/')
    
    try:
        # Récupérer tous les packages
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        if not isinstance(db, dict):
            db = {'packages': []}
        
        packages = db.get('packages', [])
        
        # Récupérer tous les utilisateurs
        users_db = GitHubManager.read_from_github('database/users.json', {'users': []})
        if not isinstance(users_db, dict):
            users_db = {'users': []}
        
        users = users_db.get('users', [])
        
        # Statistiques
        total_packages = len(packages)
        total_users = len(users)
        total_downloads = sum(p.get('downloads', 0) for p in packages)
        
        # Packages par auteur
        authors = {}
        for pkg in packages:
            author = pkg.get('author', 'unknown')
            if author not in authors:
                authors[author] = {'count': 0, 'downloads': 0}
            authors[author]['count'] += 1
            authors[author]['downloads'] += pkg.get('downloads', 0)
        
        # Trier les auteurs par nombre de packages
        top_authors = sorted(authors.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
        
        return render_template('edit_community.html',
                             user=user,
                             packages=packages,
                             users=users,
                             total_packages=total_packages,
                             total_users=total_users,
                             total_downloads=total_downloads,
                             top_authors=top_authors,
                             now=datetime.now())
    
    except Exception as e:
        app.logger.error(f"Edit community error: {e}")
        flash('Error loading community data', 'error')
        return redirect('/dashboard')
@app.route('/package/download/<scope>/<name>/<version>/<release>/<arch>')
@rate_limit()
def download_package(scope, name, version, release, arch):
    """Télécharge un fichier package en utilisant tous les identifiants."""
    try:
        filename = f"{name}-{version}-{release}-{arch}.tar.bool"
        pkg_path = f"packages/{scope}/{name}/{filename}"
        
        app.logger.info(f"📥 Download requested: {pkg_path}")
        
        # Vérifier d'abord si le package existe dans la base de données
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        package_found = None
        
        if isinstance(db, dict) and 'packages' in db:
            for pkg in db['packages']:
                if (pkg['name'] == name and 
                    pkg['version'] == version and 
                    pkg.get('release') == release and 
                    pkg.get('arch') == arch):
                    package_found = pkg
                    break
        
        if not package_found:
            app.logger.warning(f"Package metadata not found in database: {name} {version}")
            # On continue quand même, le fichier pourrait exister sans métadonnées
        
        # Lire le contenu binaire depuis GitHub
        file_content = GitHubManager.read_from_github(pkg_path, binary=True)
        
        if file_content is None:
            app.logger.error(f"❌ Package file not found: {pkg_path}")
            
            # Chercher des fichiers similaires pour aider l'utilisateur
            similar_files = []
            base_path = f"packages/{scope}/{name}/"
            # Logique pour lister les fichiers similaires (optionnel)
            
            flash(f'Package file not found: {filename}', 'error')
            return render_template('package.html',
                                 package=package_found or {'name': name, 'version': version, 'release': release, 'arch': arch, 'scope': scope},
                                 error=f"File {filename} not found on server",
                                 similar_files=similar_files), 404
        
        # ✅ Incrémenter le compteur de téléchargements (version asynchrone)
        if package_found:
            try:
                # Mise à jour asynchrone pour ne pas bloquer le téléchargement
                import threading
                def increment_download():
                    try:
                        package_found['downloads'] = package_found.get('downloads', 0) + 1
                        GitHubManager.save_to_github('database/zenv_hub.json', db, 
                                                    f"Increment download count for {name} v{version}")
                        app.logger.info(f"✅ Download count incremented for {name}")
                    except Exception as e:
                        app.logger.error(f"Failed to increment download count: {e}")
                
                # Lancer dans un thread séparé
                thread = threading.Thread(target=increment_download)
                thread.daemon = True
                thread.start()
                
            except Exception as e:
                app.logger.error(f"Failed to start download counter thread: {e}")
        
        # 📊 Statistiques de téléchargement (optionnel)
        app.logger.info(f"✅ Download successful: {filename} ({len(file_content)} bytes)")
        
        # Envoyer le fichier
        response = make_response(file_content)
        response.headers.set('Content-Type', 'application/gzip')
        response.headers.set('Content-Disposition', f'attachment; filename={filename}')
        response.headers.set('Content-Length', str(len(file_content)))
        response.headers.set('X-Download-Count', str(package_found.get('downloads', 0) + 1 if package_found else 0))
        
        return response
        
    except Exception as e:
        app.logger.error(f"🔥 Download error: {str(e)}")
        flash(f'Error downloading package: {str(e)}', 'error')
        
        # En cas d'erreur, essayer de récupérer les infos du package pour afficher une page
        try:
            db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
            package_info = None
            if isinstance(db, dict) and 'packages' in db:
                for pkg in db['packages']:
                    if pkg['name'] == name:
                        package_info = pkg
                        break
            
            return render_template('package.html',
                                 package=package_info or {'name': name, 'version': version, 'release': release, 'arch': arch, 'scope': scope},
                                 error=f"Download failed: {str(e)}"), 500
        except:
            return render_template('error.html', error=str(e)), 500

# ============================================================================
# GESTION DES ERREURS
# ============================================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"500 error: {e}")
    return render_template('500.html'), 500

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({'error': 'Rate limit exceeded'}), 429

# ============================================================================
# ROUTES DE DÉBOGAGE (À DÉSACTIVER EN PRODUCTION)
# ============================================================================

@app.route('/debug/db')
def debug_db():
    """Debug uniquement - À désactiver en production"""
    if not app.debug:
        abort(404)
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    return jsonify(db)

@app.route('/debug/session')
def debug_session():
    """Debug uniquement"""
    if not app.debug:
        abort(404)
    return jsonify({
        'session': dict(session),
        'user': session.get('user'),
        'token': session.get('token')
    })

# ============================================================================
# INITIALISATION
# ============================================================================

def init_storage():
    """Initialise les dossiers de stockage"""
    os.makedirs('/tmp/zarch_uploads', exist_ok=True)
    os.makedirs('/tmp/zarch_temp', exist_ok=True)
    
    # Vérifier la base de données GitHub
    if not GitHubManager.read_from_github('database/zenv_hub.json'):
        GitHubManager.save_to_github('database/zenv_hub.json', {
            'packages': [],
            'version': '5.2',
            'updated_at': datetime.now().isoformat()
        })

if __name__ == '__main__':
    init_storage()
    
    print("🚀 Zarch Server v5.2 Started")
    print("=" * 50)
    print(f"📦 GitHub Repo: {SecurityConfig.GITHUB_REPO}")
    print(f"🔒 Session timeout: {SecurityConfig.SESSION_TIMEOUT}s")
    print(f"🔑 Token expiry: {SecurityConfig.TOKEN_EXPIRY}s")
    print(f"📁 Max upload: {SecurityConfig.MAX_CONTENT_LENGTH // (1024*1024)}MB")
    print(f"🌐 API version: /v5.2/")
    print(f"🔗 http://localhost:10000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
