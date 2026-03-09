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
from urllib.parse import urlparse, urlencode, quote

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

from datetime import datetime, timedelta
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
    SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 360020312888))  # 1 heure
    TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 604800888888888))  # 7 jours
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB
    RATE_LIMIT = int(os.environ.get('RATE_LIMIT', 210087))  # Requêtes par minute
    COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'False').lower() == 'true'
    COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'Lax')

DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '1467542922139537469')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'https://gsql-badge.onrender.com/auth/discord/callback')
DISCORD_API_ENDPOINT = os.environ.get('DISCORD_API_ENDPOINT', 'https://discord.com/api/v10')
DISCORD_SCOPE = 'identify email guilds'
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
def generate_pkce():
    """Génère un code verifier et challenge PKCE"""
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip('=')
    return code_verifier, code_challenge


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
# GESTION DES COOKIES SÉCURISÉS (VERSION CORRIGÉE)
# ============================================================================

class CookieManager:
    @staticmethod
    def set_secure_cookie(response, name, value, max_age=3600):
        """Définit un cookie sécurisé avec chiffrement"""
        try:
            # S'assurer que la valeur est une chaîne
            if not isinstance(value, str):
                value = str(value)
            
            # Chiffrer la valeur
            encrypted = fernet.encrypt(value.encode()).decode()
            
            # Définir le cookie avec les bons paramètres
            response.set_cookie(
                name,
                encrypted,
                max_age=max_age,
                secure=SecurityConfig.COOKIE_SECURE,
                httponly=True,
                samesite=SecurityConfig.COOKIE_SAMESITE,
                path='/'
            )
            app.logger.info(f"Cookie {name} set successfully")
            return response
        except Exception as e:
            app.logger.error(f"Failed to set cookie {name}: {e}")
            return response
    
    @staticmethod
    def get_secure_cookie(request, name):
        """Récupère et déchiffre un cookie"""
        encrypted = request.cookies.get(name)
        if not encrypted:
            app.logger.debug(f"Cookie {name} not found")
            return None
        
        try:
            # Nettoyer la valeur (enlever les espaces éventuels)
            encrypted = encrypted.strip()
            
            # Déchiffrer
            decrypted = fernet.decrypt(encrypted.encode()).decode()
            app.logger.debug(f"Cookie {name} decrypted successfully")
            return decrypted
        except Exception as e:
            app.logger.warning(f"Failed to decrypt cookie {name}: {e}")
            return None
    
    @staticmethod
    def delete_secure_cookie(response, name):
        """Supprime un cookie"""
        response.set_cookie(name, '', expires=0, path='/')
        app.logger.info(f"Cookie {name} deleted")
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
# =============================================
# ROUTES DISCORD OAUTH2
# ============================================================================

@app.route('/auth/discord')
def auth_discord():
    """Redirige vers Discord pour l'authentification"""
    # Générer PKCE pour sécurité
    code_verifier, code_challenge = generate_pkce()
    
    # Stocker le verifier en session pour vérification later
    session['discord_code_verifier'] = code_verifier
    session['discord_state'] = secrets.token_urlsafe(16)
    
    # Paramètres OAuth2
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': DISCORD_SCOPE,
        'state': session['discord_state'],
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'prompt': 'consent'  # Force la demande de consentement
    }
    
    auth_url = f"{DISCORD_API_ENDPOINT}/oauth2/authorize?{urlencode(params)}"
    return redirect(auth_url)

@app.route('/auth/discord/callback')
def auth_discord_callback():
    """Callback après authentification Discord"""
    # Vérifier les paramètres
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if error:
        app.logger.error(f"Discord auth error: {error}")
        flash(f'Discord authentication failed: {error}', 'error')
        return redirect('/login')
    
    # Vérifier l'état pour prévenir CSRF
    if not state or state != session.get('discord_state'):
        app.logger.error("Invalid state parameter")
        flash('Invalid authentication state', 'error')
        return redirect('/login')
    
    if not code:
        app.logger.error("No code received")
        flash('No authorization code received', 'error')
        return redirect('/login')
    
    # Récupérer le code verifier
    code_verifier = session.get('discord_code_verifier')
    if not code_verifier:
        app.logger.error("No code verifier found")
        flash('Invalid session', 'error')
        return redirect('/login')
    
    try:
        # Échanger le code contre un token
        token_data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI,
            'code_verifier': code_verifier
        }
        
        token_response = requests.post(
            f"{DISCORD_API_ENDPOINT}/oauth2/token",
            data=token_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        if token_response.status_code != 200:
            app.logger.error(f"Token exchange failed: {token_response.text}")
            flash('Failed to get access token', 'error')
            return redirect('/login')
        
        tokens = token_response.json()
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 604800)
        
        # Récupérer les informations de l'utilisateur Discord
        user_response = requests.get(
            f"{DISCORD_API_ENDPOINT}/users/@me",
            headers={'Authorization': f'Bearer {access_token}'}
        )
        
        if user_response.status_code != 200:
            app.logger.error(f"Failed to get user info: {user_response.text}")
            flash('Failed to get user information', 'error')
            return redirect('/login')
        
        discord_user = user_response.json()
        
        # Récupérer l'email (nécessite scope email)
        email = discord_user.get('email')
        
        # Vérifier si l'utilisateur existe déjà dans notre DB
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        
        # Chercher l'utilisateur par Discord ID
        existing_user = None
        for u in db.get('users', []):
            if u.get('discord_id') == discord_user['id']:
                existing_user = u
                break
            elif u.get('email') == email and email:
                # Lier le compte Discord à l'utilisateur existant
                u['discord_id'] = discord_user['id']
                u['discord_avatar'] = f"https://cdn.discordapp.com/avatars/{discord_user['id']}/{discord_user['avatar']}.png" if discord_user.get('avatar') else None
                u['discord_username'] = discord_user['username']
                existing_user = u
                break
        
        if existing_user:
            # Mettre à jour les informations
            existing_user['last_login'] = datetime.now().isoformat()
            existing_user['discord_token'] = access_token
            existing_user['discord_refresh_token'] = refresh_token
            existing_user['discord_token_expires'] = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
            
            user = existing_user
            message = f"Welcome back, {user['username']}!"
        else:
            # Créer un nouvel utilisateur
            new_user = {
                'id': str(uuid.uuid4()),
                'username': discord_user['username'],
                'email': email,
                'discord_id': discord_user['id'],
                'discord_username': discord_user['username'],
                'discord_avatar': f"https://cdn.discordapp.com/avatars/{discord_user['id']}/{discord_user['avatar']}.png" if discord_user.get('avatar') else None,
                'discord_token': access_token,
                'discord_refresh_token': refresh_token,
                'discord_token_expires': (datetime.now() + timedelta(seconds=expires_in)).isoformat(),
                'role': 'user',
                'created_at': datetime.now().isoformat(),
                'last_login': datetime.now().isoformat(),
                'provider': 'discord'
            }
            
            db['users'].append(new_user)
            user = new_user
            message = f"Welcome to Zarch Hub, {user['username']}!"
        
        # Sauvegarder dans GitHub
        GitHubManager.save_to_github('database/users.json', db, f"Discord login: {user['username']}")
        
        # Générer notre token JWT
        jwt_token = SecurityUtils.generate_token(user['username'], user.get('role', 'user'))
        
        # Créer la session
        session['user'] = user
        session['token'] = jwt_token
        session.permanent = True
        
        # Nettoyer la session Discord
        session.pop('discord_state', None)
        session.pop('discord_code_verifier', None)
        
        # Créer la réponse avec cookie sécurisé
        response = make_response(redirect('/dashboard'))
        CookieManager.set_secure_cookie(response, 'zarch_token', jwt_token, SecurityConfig.TOKEN_EXPIRY)
        
        flash(message, 'success')
        return response
        
    except Exception as e:
        app.logger.error(f"Discord callback error: {e}")
        flash('An error occurred during Discord authentication', 'error')
        return redirect('/login')

@app.route('/auth/discord/refresh')
@token_required
def auth_discord_refresh():
    """Rafraîchir le token Discord"""
    user = g.user
    if not user.get('discord_refresh_token'):
        return jsonify({'error': 'No refresh token'}), 400
    
    try:
        refresh_data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': user['discord_refresh_token']
        }
        
        response = requests.post(
            f"{DISCORD_API_ENDPOINT}/oauth2/token",
            data=refresh_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        if response.status_code == 200:
            tokens = response.json()
            
            # Mettre à jour l'utilisateur
            db = GitHubManager.read_from_github('database/users.json', {'users': []})
            for u in db['users']:
                if u.get('discord_id') == user.get('discord_id'):
                    u['discord_token'] = tokens['access_token']
                    if 'refresh_token' in tokens:
                        u['discord_refresh_token'] = tokens['refresh_token']
                    u['discord_token_expires'] = (datetime.now() + timedelta(seconds=tokens['expires_in'])).isoformat()
                    break
            
            GitHubManager.save_to_github('database/users.json', db, f"Token refresh: {user['username']}")
            
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to refresh token'}), 400
            
    except Exception as e:
        app.logger.error(f"Token refresh error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/auth/discord/revoke')
@token_required
def auth_discord_revoke():
    """Révoquer l'accès Discord"""
    user = g.user
    if not user.get('discord_token'):
        return jsonify({'error': 'No Discord token'}), 400
    
    try:
        # Révoquer le token
        requests.post(
            f"{DISCORD_API_ENDPOINT}/oauth2/token/revoke",
            data={
                'client_id': DISCORD_CLIENT_ID,
                'client_secret': DISCORD_CLIENT_SECRET,
                'token': user['discord_token']
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        # Supprimer les infos Discord de l'utilisateur
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        for u in db['users']:
            if u.get('discord_id') == user.get('discord_id'):
                u.pop('discord_token', None)
                u.pop('discord_refresh_token', None)
                u.pop('discord_token_expires', None)
                break
        
        GitHubManager.save_to_github('database/users.json', db, f"Token revoke: {user['username']}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        app.logger.error(f"Token revoke error: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# API ENDPOINTS POUR DISCORD
# ============================================================================

@app.route('/api/v1/user/discord')
@token_required
def api_user_discord():
    """Récupérer les infos Discord de l'utilisateur"""
    user = g.user
    if not user.get('discord_id'):
        return jsonify({'connected': False})
    
    # Vérifier si le token est expiré
    token_expires = user.get('discord_token_expires')
    if token_expires:
        expires = datetime.fromisoformat(token_expires)
        if datetime.now() > expires:
            return jsonify({
                'connected': True,
                'expired': True,
                'user': {
                    'id': user['discord_id'],
                    'username': user.get('discord_username'),
                    'avatar': user.get('discord_avatar')
                }
            })
    
    return jsonify({
        'connected': True,
        'expired': False,
        'user': {
            'id': user['discord_id'],
            'username': user.get('discord_username'),
            'avatar': user.get('discord_avatar')
        }
    })

# ============================================================================
# MISE À JOUR DU TEMPLATE LOGIN.HTML
# ============================================================================

# Ajouter ce bloc dans la section des boutons sociaux
"""
<div class="grid grid-cols-3 gap-3">
    <a href="{{ url_for('auth_discord') }}" 
       class="social-btn discord flex items-center justify-center p-3 border-2 border-gray-200 dark:border-gray-700 rounded-xl hover:border-indigo-500 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-all duration-300 transform hover:scale-105 group">
        <i class="fab fa-discord text-2xl text-indigo-600 group-hover:text-indigo-700 transition-colors"></i>
    </a>
    <!-- Autres boutons sociaux -->
</div>
"""

# ============================================================================
# GESTION DES ERREURS DISCORD
# ============================================================================

@app.errorhandler(401)
def unauthorized_error(e):
    """Gérer les erreurs 401"""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': 'Unauthorized'}), 401
    flash('Please login to continue', 'info')
    return redirect('/login')

# ============================================================================
# MIDDLEWARE DE VÉRIFICATION DES TOKENS DISCORD
# ============================================================================

@app.before_request
def check_discord_tokens():
    """Vérifie l'expiration des tokens Discord"""
    if session.get('user') and session['user'].get('discord_token_expires'):
        expires = datetime.fromisoformat(session['user']['discord_token_expires'])
        if datetime.now() > expires:
            # Token expiré, essayer de rafraîchir en arrière-plan
            try:
                # Rafraîchissement asynchrone (simplifié)
                app.logger.info(f"Discord token expired for {session['user']['username']}")
                # Laisser le refresh endpoint gérer ça
            except Exception as e:
                app.logger.error(f"Token refresh failed: {e}")
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

@app.route('/package/<name>/reviews')
def package_reviews(name):
    """Page des reviews d'un package"""
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    package = next((p for p in db.get('packages', []) if p['name'] == name), None)
    
    if not package:
        abort(404)
    
    # Récupérer les reviews
    reviews_db = GitHubManager.read_from_github(f'reviews/{name}.json', {'reviews': [], 'average': 0})
    
    return render_template('reviews.html', package=package, reviews=reviews_db)

@app.route('/api/v1/package/<name>/review', methods=['POST'])
@token_required
def add_review(name):
    """Ajouter une review"""
    user = g.user
    data = request.get_json()
    
    rating = data.get('rating')
    comment = data.get('comment', '')
    
    if not rating or rating < 1 or rating > 5:
        return jsonify({'error': 'Invalid rating'}), 400
    
    # Sauvegarder la review
    reviews_db = GitHubManager.read_from_github(f'reviews/{name}.json', {'reviews': [], 'average': 0})
    
    # Vérifier si l'utilisateur a déjà reviewé
    for r in reviews_db['reviews']:
        if r['username'] == user['username']:
            return jsonify({'error': 'Already reviewed'}), 400
    
    review = {
        'username': user['username'],
        'rating': rating,
        'comment': comment,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    reviews_db['reviews'].append(review)
    
    # Recalculer la moyenne
    total = sum(r['rating'] for r in reviews_db['reviews'])
    reviews_db['average'] = total / len(reviews_db['reviews'])
    
    GitHubManager.save_to_github(f'reviews/{name}.json', reviews_db, f"New review for {name}")
    
    return jsonify({'success': True, 'average': reviews_db['average']})

@app.route('/api/v1/package/<name>/rating')
def get_rating(name):
    """Récupérer la note moyenne"""
    reviews_db = GitHubManager.read_from_github(f'reviews/{name}.json', {'reviews': [], 'average': 0})
    return jsonify({
        'average': reviews_db['average'],
        'count': len(reviews_db['reviews'])
    })
@app.route('/packages')
def packages_page():
    """Page de liste des packages avec recherche et filtres"""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    query = request.args.get('q', '').strip().lower()
    sort = request.args.get('sort', 'recent')
    scope_filter = request.args.get('scope', 'all')
    
    try:
        # Récupérer la base de données
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        
        if not isinstance(db, dict):
            db = {'packages': []}
        
        packages = db.get('packages', [])
        
        # Statistiques globales
        total_packages = len(packages)
        total_downloads = sum(p.get('downloads', 0) for p in packages)
        total_authors = len(set(p.get('author') for p in packages if p.get('author')))
        
        # Filtrer par scope
        if scope_filter != 'all':
            packages = [p for p in packages if p.get('scope') == scope_filter]
        
        # RECHERCHE PAR TEXTE (la partie importante !)
        if query:
            search_terms = query.split()
            filtered_packages = []
            
            for pkg in packages:
                name = pkg.get('name', '').lower()
                description = pkg.get('description', '').lower()
                author = pkg.get('author', '').lower()
                
                # Score de pertinence
                score = 0
                
                for term in search_terms:
                    if term in name:
                        score += 10  # Nom = très pertinent
                    if term in description:
                        score += 3   # Description = pertinent
                    if term in author:
                        score += 5   # Auteur = pertinent
                    if name.startswith(term):
                        score += 5   # Commence par = pertinent
                
                if score > 0:
                    pkg['_score'] = score
                    filtered_packages.append(pkg)
            
            # Trier par score
            packages = sorted(filtered_packages, key=lambda x: x.get('_score', 0), reverse=True)
            
            # Nettoyer le score
            for pkg in packages:
                if '_score' in pkg:
                    del pkg['_score']
        
        # Appliquer le tri
        if sort == 'downloads':
            packages.sort(key=lambda x: x.get('downloads', 0), reverse=True)
        elif sort == 'name':
            packages.sort(key=lambda x: x.get('name', '').lower())
        elif sort == 'name_desc':
            packages.sort(key=lambda x: x.get('name', '').lower(), reverse=True)
        else:  # recent par défaut
            packages.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # Pagination
        total_results = len(packages)
        total_pages = (total_results + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        paginated_packages = packages[start:end]
        
        return render_template('packages.html',
                             packages=paginated_packages,
                             total_packages=total_packages,
                             total_downloads=total_downloads,
                             total_authors=total_authors,
                             total_results=total_results,
                             total_pages=total_pages,
                             page=page,
                             per_page=per_page,
                             query=query,
                             sort=sort,
                             scope=scope_filter,
                             now=datetime.now())
    
    except Exception as e:
        app.logger.error(f"Packages page error: {e}")
        flash('Error loading packages', 'error')
        return render_template('packages.html',
                             packages=[],
                             total_packages=0,
                             total_downloads=0,
                             total_authors=0,
                             total_results=0,
                             total_pages=1,
                             page=1,
                             per_page=12,
                             query=query,
                             sort=sort,
                             scope=scope_filter,
                             now=datetime.now())

@app.route('/api/v1/packages/search')
def api_packages_search():
    """API endpoint pour la recherche en temps réel"""
    query = request.args.get('q', '').strip().lower()
    
    if not query or len(query) < 2:
        return jsonify({'results': []})
    
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    packages = db.get('packages', [])
    
    results = []
    for pkg in packages:
        name = pkg.get('name', '').lower()
        description = pkg.get('description', '').lower()
        
        if query in name or query in description:
            results.append({
                'name': pkg.get('name'),
                'version': pkg.get('version'),
                'author': pkg.get('author'),
                'downloads': pkg.get('downloads', 0),
                'scope': pkg.get('scope', 'public'),
                'url': f"/package/{pkg.get('name')}"
            })
            
            if len(results) >= 10:  # Limiter à 10 résultats
                break
    
    return jsonify({'results': results})
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
@token_required
def dashboard_page():
    """Dashboard utilisateur avec toutes les fonctionnalités"""
    user = g.user
    username = user['username']
    
    try:
        # =====================================================================
        # 1. CHARGEMENT DES DONNÉES UTILISATEUR
        # =====================================================================
        # Récupérer la base de données des utilisateurs
        users_db = GitHubManager.read_from_github('database/users.json', {'users': []})
        current_user = next((u for u in users_db.get('users', []) if u['username'] == username), user)
        
        # =====================================================================
        # 2. CHARGEMENT DES PACKAGES DE L'UTILISATEUR
        # =====================================================================
        packages_db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        all_packages = packages_db.get('packages', [])
        
        # Packages de l'utilisateur
        user_packages = [p for p in all_packages if p.get('author') == username]
        
        # Statistiques
        total_packages = len(user_packages)
        total_downloads = sum(p.get('downloads', 0) for p in user_packages)
        
        # =====================================================================
        # 3. CHARGEMENT DES BADGES PERSONNALISÉS
        # =====================================================================
        badges = GitHubManager.read_from_github(f'badges/{username}/badges.json', {})
        badges_count = len(badges)
        
        # =====================================================================
        # 4. CHARGEMENT DES REVIEWS
        # =====================================================================
        reviews_count = 0
        recent_reviews = []
        
        for package in user_packages:
            package_reviews = GitHubManager.read_from_github(f'reviews/{package["name"]}.json', {'reviews': []})
            reviews_count += len(package_reviews.get('reviews', []))
            
            # Ajouter les 3 dernières reviews
            for review in package_reviews.get('reviews', [])[:3]:
                recent_reviews.append({
                    'author': review.get('username'),
                    'package': package['name'],
                    'rating': review.get('rating'),
                    'comment': review.get('comment'),
                    'time': review.get('created_at', '')[:10]
                })
        
        # Trier par date et limiter
        recent_reviews = sorted(recent_reviews, key=lambda x: x['time'], reverse=True)[:5]
        
        # =====================================================================
        # 5. CHARGEMENT DE L'ACTIVITÉ RÉCENTE
        # =====================================================================
        recent_activity = []
        
        # Activité des packages récents
        for pkg in sorted(user_packages, key=lambda x: x.get('created_at', ''), reverse=True)[:3]:
            recent_activity.append({
                'icon': 'upload',
                'color': 'purple',
                'message': f'Published <span class="font-medium">{pkg["name"]} v{pkg["version"]}</span>',
                'time': pkg.get('created_at', '')[:10]
            })
        
        # Activité des téléchargements (simulée)
        if total_downloads > 0:
            recent_activity.append({
                'icon': 'download',
                'color': 'green',
                'message': f'Reached <span class="font-medium">{total_downloads}</span> total downloads',
                'time': 'Today'
            })
        
        # Activité des badges
        if badges_count > 0:
            recent_activity.append({
                'icon': 'award',
                'color': 'yellow',
                'message': f'Created <span class="font-medium">{badges_count}</span> custom badges',
                'time': 'Recently'
            })
        
        # =====================================================================
        # 6. DONNÉES COMMUNAUTAIRES
        # =====================================================================
        # Top contributeurs
        author_stats = {}
        for pkg in all_packages:
            author = pkg.get('author')
            if author:
                if author not in author_stats:
                    author_stats[author] = 0
                author_stats[author] += 1
        
        top_contributors = []
        for author, count in sorted(author_stats.items(), key=lambda x: x[1], reverse=True)[:5]:
            top_contributors.append({
                'username': author,
                'packages': count
            })
        
        # Statistiques communautaires
        online_members = len(set(p.get('author') for p in all_packages))  # Simulé
        new_packages_today = len([p for p in all_packages if p.get('created_at', '').startswith(datetime.now().strftime('%Y-%m-%d'))])
        active_discussions = 8  # Simulé
        new_badges_today = 3  # Simulé
        
        # Notifications communautaires
        community_notifications = [
            {
                'icon': 'users',
                'color': 'blue',
                'message': f'<span class="font-medium">{online_members}</span> contributors active',
                'time': 'Now'
            },
            {
                'icon': 'box',
                'color': 'purple',
                'message': f'<span class="font-medium">{new_packages_today}</span> new packages today',
                'time': 'Today'
            },
            {
                'icon': 'comments',
                'color': 'green',
                'message': 'New discussion in #general',
                'time': '2h ago'
            }
        ]
        
        # =====================================================================
        # 7. DONNÉES POUR LES GRAPHIQUES
        # =====================================================================
        # Simuler des données de téléchargements pour les 30 derniers jours
        import random
        from datetime import timedelta
        
        chart_labels = []
        chart_data = []
        
        for i in range(30, 0, -1):
            date = (datetime.now() - timedelta(days=i)).strftime('%d/%m')
            chart_labels.append(date)
            chart_data.append(random.randint(0, 20))  # Simulé
        
        popular_labels = [p['name'] for p in user_packages[:3]] if user_packages else ['apkm', 'bool', 'apsm']
        popular_data = [p.get('downloads', 0) for p in user_packages[:3]] if user_packages else [42, 15, 7]
        
        # =====================================================================
        # 8. STATISTIQUES PACKAGÉES
        # =====================================================================
        stats = {
            'packages': total_packages,
            'downloads': total_downloads,
            'member_since': user.get('created_at', '2026')[:10]
        }
        
        # =====================================================================
        # 9. VÉRIFICATION ADMIN
        # =====================================================================
        is_admin = username in ['admin', 'gopu-inc', 'mauricio', 'mauricio_tukss1231', 'Mauricio-100']
        
        # =====================================================================
        # 10. RENDU DU TEMPLATE AVEC TOUTES LES DONNÉES
        # =====================================================================
        return render_template('dashboard.html',
                             user=current_user,
                             user_packages=user_packages,
                             stats=stats,
                             chart_labels=chart_labels,
                             chart_data=chart_data,
                             popular_labels=popular_labels,
                             popular_data=popular_data,
                             badges=badges,
                             badges_count=badges_count,
                             recent_reviews=recent_reviews,
                             reviews_count=reviews_count,
                             recent_activity=recent_activity,
                             top_contributors=top_contributors,
                             online_members=online_members,
                             new_packages=new_packages_today,
                             active_discussions=active_discussions,
                             new_badges=new_badges_today,
                             community_notifications=community_notifications,
                             is_admin=is_admin,
                             now=datetime.now())
    
    except Exception as e:
        app.logger.error(f"Dashboard error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Données par défaut en cas d'erreur
        default_stats = {
            'packages': 0,
            'downloads': 0,
            'member_since': user.get('created_at', '2026')[:10]
        }
        
        return render_template('dashboard.html',
                             user=user,
                             user_packages=[],
                             stats=default_stats,
                             chart_labels=['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                             chart_data=[0, 0, 0, 0, 0, 0],
                             popular_labels=['apkm', 'bool', 'apsm'],
                             popular_data=[0, 0, 0],
                             badges={},
                             badges_count=0,
                             recent_reviews=[],
                             reviews_count=0,
                             recent_activity=[],
                             top_contributors=[],
                             online_members=0,
                             new_packages=0,
                             active_discussions=0,
                             new_badges=0,
                             community_notifications=[],
                             is_admin=(username in ['admin', 'gopu-inc', 'mauricio']),
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
@app.route('/@<username>')
def user_profile(username):
    """Profil public d'un utilisateur"""
    # Récupérer l'utilisateur
    db = GitHubManager.read_from_github('database/users.json', {'users': []})
    user = next((u for u in db['users'] if u['username'] == username), None)
    
    if not user:
        abort(404)
    
    # Récupérer ses packages
    packages_db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    user_packages = [p for p in packages_db.get('packages', []) if p['author'] == username]
    
    # Statistiques
    total_downloads = sum(p.get('downloads', 0) for p in user_packages)
    total_packages = len(user_packages)
    
    # Badges personnalisés
    badges_db = GitHubManager.read_from_github(f'badges/{username}/badges.json', {})
    
    # Activité récente (à implémenter)
    recent_activity = []
    
    return render_template('profile.html',
                         profile_user=user,
                         packages=user_packages,
                         total_downloads=total_downloads,
                         total_packages=total_packages,
                         badges=badges_db,
                         activity=recent_activity,
                         now=datetime.now())
@app.route('/settings/badges/create', methods=['GET', 'POST'])
@token_required
def create_custom_badge():
    """Atelier de création de badges"""
    user = g.user
    
    if request.method == 'POST':
        badge_data = {
            'name': request.form['name'],
            'label': request.form['label'],
            'value': request.form['value'],
            'color': request.form['color'],
            'description': request.form.get('description', ''),
            'created_at': datetime.now().isoformat(),
            'usage_count': 0
        }
        
        # Sauvegarder le badge
        db = GitHubManager.read_from_github(f'badges/{user["username"]}/badges.json', {})
        db[badge_data['name']] = badge_data
        GitHubManager.save_to_github(
            f'badges/{user["username"]}/badges.json', 
            db, 
            f"New badge: {badge_data['name']}"
        )
        
        flash('Badge created successfully!', 'success')
        return redirect(f'/settings/badges/{badge_data["name"]}')
    
    return render_template('create_badge.html', user=user)


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

@app.route('/install.sh')
def install_script():
    """Script d'installation automatique pour APKM/APSM/BOOL"""
    script = """#!/bin/sh
# Zarch Hub Auto-Installer
set -e

echo "🚀 Zarch Hub Installer"
echo "======================"

# Couleurs
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m'

# Vérification des permissions
if [ "$EUID" -ne 0 ]; then 
    echo "${RED}❌ Please run as root${NC}"
    exit 1
fi

echo "${BLUE}📦 Installing APKM Tools...${NC}"

# Détection de l'architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)  ARCH="x86_64" ;;
    aarch64) ARCH="arm64" ;;
    armv7l)  ARCH="armv7" ;;
    *)       echo "${RED}❌ Unsupported architecture: $ARCH${NC}"; exit 1 ;;
esac

echo "${YELLOW}🔧 Architecture detected: $ARCH${NC}"

# URLs des binaires
BASE_URL="https://gsql-badge.onrender.com/package/download/public"
VERSION="2.0.0"
RELEASE="r1"

# Installation d'APKM
echo "${BLUE}📥 Downloading APKM...${NC}"
curl -L -o /tmp/apkm.tar.bool "$BASE_URL/apkm/$VERSION/$RELEASE/$ARCH"
tar -xzf /tmp/apkm.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xf /tmp/apkm.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/apkm
rm -f /tmp/apkm.tar.bool

# Installation d'APSM
echo "${BLUE}📥 Downloading APSM...${NC}"
curl -L -o /tmp/apsm.tar.bool "$BASE_URL/apsm/$VERSION/$RELEASE/$ARCH"
tar -xzf /tmp/apsm.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xf /tmp/apsm.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/apsm
rm -f /tmp/apsm.tar.bool

# Installation de BOOL
echo "${BLUE}📥 Downloading BOOL...${NC}"
curl -L -o /tmp/bool.tar.bool "$BASE_URL/bool/$VERSION/$RELEASE/$ARCH"
tar -xzf /tmp/bool.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xf /tmp/bool.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/bool
rm -f /tmp/bool.tar.bool

# Création des répertoires
mkdir -p /usr/local/share/apkm/{database,cache,PROTOCOLE/security/tokens}

# Configuration initiale
echo "${BLUE}⚙️  Configuring APKM...${NC}"
cat > /etc/apkm/repositories.conf << EOF
# APKM Repositories
zarch-hub https://gsql-badge.onrender.com 5
EOF

# Vérification
echo "${GREEN}✅ Installation complete!${NC}"
echo ""
echo "📋 Commands installed:"
echo "   $(which apkm) - Package manager"
echo "   $(which apsm) - Publisher"
echo "   $(which bool) - Builder"
echo ""
echo "🚀 Try: apkm --help"
echo "🔐 Login: apsm login"
echo "🏗️ build: bool --verify"
echo "${YELLOW}📊 Statistics:${NC}"
apkm --version
"""
    
    return Response(script, mimetype='text/plain', headers={
        'Content-Disposition': 'attachment; filename="install.sh"',
        'Cache-Control': 'no-cache'
    })

@app.route('/badge/<path:badge_name>')
def serve_badge_svg(badge_name):
    """Génère un badge SVG dynamique"""
    from badges import BadgeGenerator
    
    # Parser le format [label]-[value]-[color]
    parts = badge_name.replace('.svg', '').split('-')
    
    if len(parts) >= 2:
        # Format: label-value-color
        if len(parts) >= 3:
            label, value, color = parts[0], '-'.join(parts[1:-1]), parts[-1]
        else:
            label, value = parts[0], parts[1]
            color = 'blue'
    else:
        label = badge_name
        value = 'unknown'
        color = 'gray'
    
    svg = BadgeGenerator.generate(label, value, color)
    return Response(svg, mimetype='image/svg+xml')

@app.route('/badge/package/<name>')
def package_badge(name):
    """Badge dynamique pour un package"""
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    package = next((p for p in db.get('packages', []) if p['name'] == name), None)
    
    if not package:
        return serve_badge_svg('package-not_found-red')
    
    version = package.get('version', 'unknown')
    downloads = package.get('downloads', 0)
    
    # Générer plusieurs badges
    badges = {
        'version': BadgeGenerator.generate('version', version, 'blue'),
        'downloads': BadgeGenerator.generate('downloads', f"{downloads}", 'green'),
        'license': BadgeGenerator.generate('license', package.get('license', 'MIT'), 'yellow')
    }
    
    return jsonify(badges)

@app.route('/badge/custom/<username>/<badge_name>')
def custom_badge(username, badge_name):
    """Badge personnalisé créé par l'utilisateur"""
    db = GitHubManager.read_from_github(f'badges/{username}/badges.json', {})
    badge = db.get(badge_name)
    
    if not badge:
        return serve_badge_svg('badge-not_found-red')
    
    svg = BadgeGenerator.generate(
        badge['label'],
        badge['value'],
        badge.get('color', 'blue')
    )
    return Response(svg, mimetype='image/svg+xml')


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

@app.route('/debug/token')
def debug_session():
    """Debug uniquement"""
    if not app.debug:
        abort(404)
    return jsonify({
        'session': dict(session),
        'user': session.get('user'),
        'token': session.get('token')
    })
@app.route('/debug/cookies')
def debug_coockies():
    """Route de debug pour vérifier la session"""
    if not app.debug:
        abort(404)
    
    return jsonify({
        'session': dict(session),
        'cookies': dict(request.cookies),
        'user': session.get('user'),
        'token': session.get('token'),
        'has_token_cookie': 'zarch_token' in request.cookies
    })

# ============================================================================
# SETTING COMPLET
# ============================================================================

@app.route('/settings')
@token_required
def settings_dashboard():
    """Dashboard des paramètres"""
    user = g.user
    return render_template('settings/index.html', user=user)

@app.route('/settings/profile', methods=['GET', 'POST'])
@token_required
def settings_profile():
    """Paramètres du profil"""
    user = g.user
    
    if request.method == 'POST':
        # Mettre à jour le profil
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        for u in db['users']:
            if u['username'] == user['username']:
                u['display_name'] = request.form.get('display_name', u['username'])
                u['bio'] = request.form.get('bio', '')
                u['website'] = request.form.get('website', '')
                u['twitter'] = request.form.get('twitter', '')
                u['github'] = request.form.get('github', '')
                u['updated_at'] = datetime.now().isoformat()
                break
        
        GitHubManager.save_to_github('database/users.json', db, f"Profile update: {user['username']}")
        flash('Profile updated successfully!', 'success')
        return redirect('/settings/profile')
    
    return render_template('settings/profile.html', user=user)

@app.route('/settings/security', methods=['GET', 'POST'])
@token_required
def settings_security():
    """Paramètres de sécurité"""
    user = g.user
    return render_template('settings/security.html', user=user)

@app.route('/settings/notifications', methods=['GET', 'POST'])
@token_required
def settings_notifications():
    """Paramètres des notifications"""
    user = g.user
    return render_template('settings/notifications.html', user=user)

@app.route('/settings/badges')
@token_required
def settings_badges():
    """Gestion des badges personnalisés"""
    user = g.user
    badges = GitHubManager.read_from_github(f'badges/{user["username"]}/badges.json', {})
    return render_template('settings/badges.html', user=user, badges=badges)

@app.route('/settings/badges/<badge_name>')
@token_required
def settings_badge_detail(badge_name):
    """Détail d'un badge"""
    user = g.user
    badges = GitHubManager.read_from_github(f'badges/{user["username"]}/badges.json', {})
    badge = badges.get(badge_name)
    
    if not badge:
        abort(404)
    
    return render_template('settings/badge_detail.html', user=user, badge=badge, name=badge_name)

@app.route('/settings/badges/<badge_name>/delete', methods=['POST'])
@token_required
def settings_badge_delete(badge_name):
    """Supprimer un badge"""
    user = g.user
    badges = GitHubManager.read_from_github(f'badges/{user["username"]}/badges.json', {})
    
    if badge_name in badges:
        del badges[badge_name]
        GitHubManager.save_to_github(
            f'badges/{user["username"]}/badges.json', 
            badges, 
            f"Deleted badge: {badge_name}"
        )
        flash('Badge deleted', 'success')
    
    return redirect('/settings/badges')

@app.route('/settings/delete-account', methods=['POST'])
@token_required
def settings_delete_account():
    """Supprimer définitivement le compte utilisateur"""
    user = g.user
    username = user['username']
    
    try:
        # 1. Vérification du mot de passe (sécurité)
        password = request.form.get('password')
        if not password:
            flash('Password is required to delete account', 'error')
            return redirect('/settings/danger')
        
        # Vérifier le mot de passe (à adapter selon ton système d'auth)
        db = GitHubManager.read_from_github('database/users.json', {'users': []})
        user_data = next((u for u in db['users'] if u['username'] == username), None)
        
        if not user_data:
            flash('User not found', 'error')
            return redirect('/settings')
        
        # Vérifier le mot de passe (si tu utilises bcrypt)
        # if not SecurityUtils.check_password(password, user_data['password']):
        #     flash('Invalid password', 'error')
        #     return redirect('/settings/danger')
        
        # 2. Demander confirmation (déjà géré par le formulaire)
        
        # 3. Supprimer tous les packages de l'utilisateur
        packages_db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        user_packages = [p for p in packages_db.get('packages', []) if p.get('author') == username]
        
        deleted_packages = 0
        for package in user_packages:
            package_name = package['name']
            
            # Supprimer le fichier du package
            package_path = f"packages/{package.get('scope', 'public')}/{package_name}/{package_name}-{package['version']}-{package.get('release', 'r0')}-{package.get('arch', 'x86_64')}.tar.bool"
            GitHubManager.delete_from_github(package_path, f"Deleted package {package_name} (account deletion)")
            
            # Supprimer les reviews du package
            GitHubManager.delete_from_github(f'reviews/{package_name}.json', f"Deleted reviews for {package_name}")
            
            deleted_packages += 1
        
        # 4. Supprimer tous les badges personnalisés
        badges = GitHubManager.read_from_github(f'badges/{username}/badges.json', {})
        if badges:
            for badge_name in badges.keys():
                # Log la suppression (pas besoin de supprimer individuellement)
                pass
            GitHubManager.delete_from_github(f'badges/{username}/badges.json', f"Deleted all badges for {username}")
            GitHubManager.delete_from_github(f'badges/{username}/', f"Deleted badge directory for {username}")
        
        # 5. Supprimer les reviews laissées par l'utilisateur
        # Parcourir tous les packages pour supprimer les reviews de l'utilisateur
        all_packages = packages_db.get('packages', [])
        for package in all_packages:
            reviews = GitHubManager.read_from_github(f'reviews/{package["name"]}.json', {'reviews': [], 'average': 0})
            if reviews.get('reviews'):
                original_count = len(reviews['reviews'])
                reviews['reviews'] = [r for r in reviews['reviews'] if r.get('username') != username]
                
                if len(reviews['reviews']) < original_count:
                    # Recalculer la moyenne
                    if reviews['reviews']:
                        total = sum(r['rating'] for r in reviews['reviews'])
                        reviews['average'] = total / len(reviews['reviews'])
                    else:
                        reviews['average'] = 0
                    
                    GitHubManager.save_to_github(
                        f'reviews/{package["name"]}.json',
                        reviews,
                        f"Removed reviews by {username} (account deletion)"
                    )
        
        # 6. Supprimer l'utilisateur de la base de données
        db['users'] = [u for u in db['users'] if u['username'] != username]
        
        # 7. Sauvegarder la base de données mise à jour
        GitHubManager.save_to_github('database/users.json', db, f"Deleted user: {username}")
        
        # 8. Nettoyer la session et les cookies
        session.clear()
        
        # Créer une réponse de redirection
        response = make_response(redirect('/'))
        
        # Supprimer le cookie
        CookieManager.delete_secure_cookie(response, 'zarch_token')
        
        # 9. Journaliser l'action
        app.logger.info(f"Account deleted: {username} (deleted {deleted_packages} packages)")
        
        # 10. Message de confirmation
        flash('Your account has been permanently deleted. We\'re sorry to see you go!', 'info')
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error deleting account {username}: {e}")
        flash(f'Error deleting account: {str(e)}', 'error')
        return redirect('/settings')
    
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
