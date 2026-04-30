#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zarch Package Registry v5.2 - Production Edition
Sécurité renforcée, API versionnée, Cookies sécurisés
Stockage GitHub préservé
"""

import re
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
from flask import Flask, request, jsonify, g, render_template, make_response, session, redirect, flash, abort, Response 
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
# Générez ces clés avec le script ci-dessous et utilisez-les DANS VOTRE ENVIRONNEMENT RENDER
    FERNET_KEY = "H7p9DlfJPZK7chq4irNFcY3W_fPLv4loxZ3DxAmlxYc="
    JWT_SECRET = "e8f2e4b8c6d4a1f9b7e3c5a7d9b1f3e5c7a9b1d3f5e7c9a1b3d5f7e9c1b3d5f7"
    APP_SECRET = "f7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b9a0f1e2d3c4b5a6f7e8d9"
    COOKIE_SECRET = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2"
    # GitHub (inchangé)
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "")
    GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/gsql-badge")
    GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package-data")
    
    # Paramètres de sécurité
    SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 960020))  # 1 heure
    TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 904800))  # 7 jours
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
    JSON_SORT_KEYS=False,
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

class CookieManager:
    @staticmethod
    def set_secure_cookie(response, name, value, max_age=3600):
        """Définit un cookie sécurisé avec chiffrement"""
        try:
            if not isinstance(value, str):
                value = str(value)
            
            # Chiffrer la valeur
            encrypted = fernet.encrypt(value.encode()).decode()
            
            # Supprimer l'ancien cookie d'abord (important !)
            response.set_cookie(name, '', expires=0, path='/')
            
            # Définir le nouveau cookie
            response.set_cookie(
                name,
                encrypted,
                max_age=max_age,
                secure=app.config.get('SESSION_COOKIE_SECURE', False),
                httponly=True,
                samesite=app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
                path='/'
            )
            app.logger.info(f"✅ Cookie {name} set successfully")
            return response
        except Exception as e:
            app.logger.error(f"❌ Failed to set cookie {name}: {e}")
            return response
    
    @staticmethod
    def get_secure_cookie(request, name):
        """Récupère et déchiffre un cookie"""
        encrypted = request.cookies.get(name)
        if not encrypted:
            return None
        
        try:
            # Nettoyer la valeur
            encrypted = encrypted.strip()
            
            # Essayer de déchiffrer
            decrypted = fernet.decrypt(encrypted.encode()).decode()
            return decrypted
        except Exception as e:
            app.logger.warning(f"⚠️ Failed to decrypt cookie {name}: {str(e)[:50]}")
            # Retourner None silencieusement - l'utilisateur devra se reconnecter
            return None
    
    @staticmethod
    def delete_secure_cookie(response, name):
        """Supprime un cookie"""
        response.set_cookie(name, '', expires=0, path='/')
        app.logger.info(f"🗑️ Cookie {name} deleted")
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
        'user_agent': request.user_agent.string[:50]
    })
    
    # Rate limiting simple
    g.request_time = datetime.now()
    
    # Éviter de traiter les routes statiques et de debug
    if request.path.startswith('/static/') or request.path.startswith('/debug/'):
        return
    
    # Vérification du token dans les cookies (avec gestion d'erreur améliorée)
    if not session.get('user'):
        token = CookieManager.get_secure_cookie(request, 'zarch_token')
        if token:
            try:
                user = SecurityUtils.validate_token(token)
                if user:
                    app.logger.info(f"✅ User {user.get('username')} authenticated via cookie")
                    session['user'] = user
                    session['token'] = token
                else:
                    app.logger.warning("⚠️ Invalid token found in cookie")
                    # Le cookie est invalide, on le supprimera dans la réponse
                    g.invalid_cookie = True
            except Exception as e:
                app.logger.error(f"🔥 Error validating token: {e}")
                g.invalid_cookie = True
@app.after_request
def after_request(response):
    """Middleware exécuté après chaque requête"""
    # Ajout des headers de sécurité
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Nettoyer les cookies invalides si nécessaire
    if hasattr(g, 'invalid_cookie') and g.invalid_cookie:
        CookieManager.delete_secure_cookie(response, 'zarch_token')
        app.logger.info("🗑️ Removed invalid cookie")
    
    # Audit logging
    duration = (datetime.now() - g.request_time).total_seconds()
    app.logger.info('Response', extra={
        'status': response.status_code,
        'duration': round(duration, 3)
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
            
            # Cookie sécurisé (CORRIGÉ)
            response = jsonify({
                'success': True,
                'token': token,
                'user': {
                    'username': user['username'],
                    'role': user.get('role', 'user'),
                    'created_at': user.get('created_at')
                }
            })
            
            # Définir le cookie
            CookieManager.set_secure_cookie(response, 'zarch_token', token, SecurityConfig.TOKEN_EXPIRY)
            
            app.logger.info(f"User {validated.username} logged in successfully, cookie set")
            
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





# ============================================================================
# ROUTE DOCUMENTATION GOSCRIPT (depuis GitHub)
# ============================================================================

@app.route('/goscript/doc')
def goscript_doc():
    """Serve the full Goscript documentation from the GitHub README"""
    try:
        app.logger.info("📖 Fetching Goscript documentation from GitHub...")
        
        # Attempt 1: Read from GitHub repository (configured branch)
        app.logger.debug("🔍 Attempt 1: Reading docs/README-GOSCRIPT.md from configured branch...")
        readme_content = GitHubManager.read_from_github(
            'docs/README-GOSCRIPT.md',
            default=None
        )
        
        if readme_content is not None:
            app.logger.debug("✅ Found docs/README-GOSCRIPT.md via GitHubManager")
        else:
            # Attempt 2: Try root of the repo
            app.logger.debug("🔍 Attempt 2: Trying README-GOSCRIPT.md at repo root...")
            readme_content = GitHubManager.read_from_github(
                'README-GOSCRIPT.md',
                default=None
            )
            
            if readme_content is not None:
                app.logger.debug("✅ Found README-GOSCRIPT.md at repo root")
        
        if readme_content is None:
            # Attempt 3: Direct raw GitHub API on the configured branch
            raw_url = f"https://raw.githubusercontent.com/{SecurityConfig.GITHUB_REPO}/{SecurityConfig.GITHUB_BRANCH}/docs/README-GOSCRIPT.md"
            app.logger.debug(f"🔍 Attempt 3: Fetching from raw URL on configured branch: {raw_url}")
            
            import requests as req
            resp = req.get(raw_url, timeout=10)
            
            if resp.status_code == 200:
                readme_content = resp.text
                app.logger.debug(f"✅ Fetched from raw URL ({len(readme_content)} bytes)")
            else:
                # Attempt 4: Try the 'main' branch as last resort
                raw_url = f"https://raw.githubusercontent.com/{SecurityConfig.GITHUB_REPO}/main/docs/README-GOSCRIPT.md"
                app.logger.debug(f"🔍 Attempt 4: Trying main branch: {raw_url}")
                
                resp = req.get(raw_url, timeout=10)
                if resp.status_code == 200:
                    readme_content = resp.text
                    app.logger.debug(f"✅ Fetched from main branch ({len(readme_content)} bytes)")
                else:
                    app.logger.warning(f"❌ All fetch attempts failed. Last status: {resp.status_code}")
        
        # If we still have nothing, return 404
        if readme_content is None:
            app.logger.error("❌ Goscript documentation not found. Please ensure docs/README-GOSCRIPT.md exists in the repository.")
            abort(404, description="Goscript documentation not found. The file docs/README-GOSCRIPT.md does not exist in the repository.")
        
        # Clean content if it's a dict (accidental JSON parsing)
        if isinstance(readme_content, dict):
            app.logger.debug("⚠️ Content was parsed as JSON dict, extracting raw content...")
            readme_content = readme_content.get('content', '') or str(readme_content)
        
        if isinstance(readme_content, str):
            app.logger.debug(f"📄 Processing markdown content ({len(readme_content)} characters, {readme_content.count(chr(10)) + 1} lines)")
        
        # Render markdown to HTML
        app.logger.debug("🖌️ Rendering markdown to HTML...")
        readme_html = MarkdownRenderer.render(readme_content)
        app.logger.debug(f"✅ Markdown rendered successfully ({len(readme_html)} bytes of HTML)")
        
        app.logger.info(f"📖 Serving Goscript documentation ({len(readme_content)} chars)")
        
        return render_template('goscript_doc.html',
                             readme_html=readme_html,
                             readme_raw=readme_content,
                             now=datetime.now(),
                             user=session.get('user'))
    
    except Exception as e:
        app.logger.error(f"❌ Goscript doc error: {type(e).__name__}: {str(e)}")
        app.logger.debug(f"Stack trace: {e.__traceback__}")
        abort(500, description=f"Error loading documentation: {str(e)}")


# ============================================================================
# ROUTE API POUR LES DÉPENDANCES D'UN PACKAGE
# ============================================================================

@app.route('/api/v1/package/<name>/dependencies')
def api_package_dependencies(name):
    """Return package dependencies extracted from Manifest.toml"""
    try:
        app.logger.debug(f"📦 Fetching dependencies for package: {name}")
        
        db = safe_read_json('database/zenv_hub.json', {'packages': []})
        
        if not isinstance(db, dict):
            app.logger.warning(f"⚠️ DB is not a dict, type: {type(db)}")
            db = {'packages': []}
        
        package = next((p for p in db.get('packages', []) if p.get('name') == name), None)
        
        if not package:
            app.logger.warning(f"⚠️ Package '{name}' not found in zenv_hub.json")
            return jsonify({'dependencies': [], 'dev_dependencies': []})
        
        app.logger.debug(f"📦 Found package: {name} v{package.get('version')} (scope: {package.get('scope')})")
        
        # Build filename and path
        filename = f"{name}-{package['version']}-{package.get('release', 'r0')}-{package.get('arch', 'x86_64')}.tar.bool"
        pkg_path = f"packages/{package['scope']}/{name}/{filename}"
        
        app.logger.debug(f"🔍 Looking for package archive: {pkg_path}")
        
        content = GitHubManager.read_from_github(pkg_path, default=None, binary=True)
        deps = []
        dev_deps = []
        
        if content:
            app.logger.debug(f"✅ Package archive found ({len(content)} bytes), extracting Manifest.toml...")
            
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, filename)
            
            try:
                with open(temp_path, 'wb') as f:
                    f.write(content)
                
                manifest_found = False
                with tarfile.open(temp_path, 'r:*') as tar:
                    for member in tar.getmembers():
                        if member.name.endswith('Manifest.toml') or member.name == 'Manifest.toml':
                            manifest_found = True
                            app.logger.debug(f"📄 Found Manifest.toml at: {member.name}")
                            
                            manifest_content = tar.extractfile(member).read().decode('utf-8', errors='ignore')
                            app.logger.debug(f"📄 Manifest.toml size: {len(manifest_content)} bytes")
                            
                            # Simple TOML parser
                            current_section = ''
                            line_number = 0
                            
                            for line in manifest_content.split('\n'):
                                line_number += 1
                                line = line.strip()
                                
                                # Skip comments and empty lines
                                if not line or line.startswith('#'):
                                    continue
                                
                                # Section header detection
                                if line.startswith('['):
                                    current_section = line.strip('[]').strip()
                                    app.logger.debug(f"  📂 Section: [{current_section}] (line {line_number})")
                                
                                # Parse key = value in dependencies section
                                elif '=' in line and current_section == 'dependencies':
                                    key, val = line.split('=', 1)
                                    dep_name = key.strip().strip('"').strip("'")
                                    dep_version = val.strip().strip('"').strip("'")
                                    deps.append({
                                        'name': dep_name,
                                        'version': dep_version,
                                        'dev': False
                                    })
                                    app.logger.debug(f"  📦 Production dependency: {dep_name} = {dep_version}")
                                
                                # Parse key = value in dev-dependencies section
                                elif '=' in line and current_section == 'dev-dependencies':
                                    key, val = line.split('=', 1)
                                    dep_name = key.strip().strip('"').strip("'")
                                    dep_version = val.strip().strip('"').strip("'")
                                    dev_deps.append({
                                        'name': dep_name,
                                        'version': dep_version,
                                        'dev': True
                                    })
                                    app.logger.debug(f"  🛠️ Dev dependency: {dep_name} = {dep_version}")
                
                if not manifest_found:
                    app.logger.debug(f"⚠️ No Manifest.toml found in archive for {name}")
                
            except tarfile.ReadError as e:
                app.logger.warning(f"⚠️ Failed to read tar archive for {name}: {e}")
            except Exception as e:
                app.logger.error(f"❌ Error processing archive for {name}: {type(e).__name__}: {e}")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
                app.logger.debug(f"🧹 Cleaned up temp directory: {temp_dir}")
        else:
            app.logger.debug(f"⚠️ Package archive not found at: {pkg_path}")
        
        app.logger.debug(f"📊 Dependencies for {name}: {len(deps)} production, {len(dev_deps)} dev")
        
        return jsonify({
            'dependencies': deps,
            'dev_dependencies': dev_deps
        })
    
    except Exception as e:
        app.logger.error(f"❌ Dependencies API error for {name}: {type(e).__name__}: {str(e)}")
        app.logger.debug(f"Stack trace: {e.__traceback__}")
        return jsonify({'dependencies': [], 'dev_dependencies': [], 'error': str(e)})


# ============================================================================
# ROUTE API POUR LES REVIEWS D'UN PACKAGE
# ============================================================================

@app.route('/api/v1/package/<name>/reviews')
def api_package_reviews(name):
    """Return all reviews for a package"""
    try:
        app.logger.debug(f"⭐ Fetching reviews for package: {name}")
        
        reviews_db = safe_read_json(f'reviews/{name}.json', {'reviews': [], 'average': 0})
        
        if not isinstance(reviews_db, dict):
            app.logger.warning(f"⚠️ Reviews DB for {name} is not a dict, type: {type(reviews_db)}")
            reviews_db = {'reviews': [], 'average': 0}
        
        review_count = len(reviews_db.get('reviews', []))
        average = reviews_db.get('average', 0)
        
        app.logger.debug(f"📊 Reviews for {name}: {review_count} reviews, average: {average}")
        
        return jsonify({
            'reviews': reviews_db.get('reviews', []),
            'average': average,
            'count': review_count
        })
    
    except Exception as e:
        app.logger.error(f"❌ Reviews API error for {name}: {type(e).__name__}: {str(e)}")
        app.logger.debug(f"Stack trace: {e.__traceback__}")
        return jsonify({'reviews': [], 'average': 0, 'count': 0, 'error': str(e)})


# ============================================================================
# ROUTE POUR AJOUTER UNE REVIEW (POST)
# ============================================================================

@app.route('/api/v1/package/<name>/review', methods=['POST'])
@token_required
def api_add_review(name):
    """Add or update a review for a package"""
    try:
        user = g.user
        username = user.get('username', 'unknown')
        
        app.logger.info(f"⭐ {username} is submitting a review for: {name}")
        
        data = request.get_json()
        
        if not data:
            app.logger.warning(f"⚠️ No JSON data in review request for {name}")
            return jsonify({'error': 'No data provided'}), 400
        
        rating = data.get('rating', 0)
        comment = data.get('comment', '').strip()
        
        app.logger.debug(f"📝 Review data - rating: {rating}, comment length: {len(comment)}")
        
        # Validate rating
        if not rating or not isinstance(rating, (int, float)) or rating < 1 or rating > 5:
            app.logger.warning(f"⚠️ Invalid rating from {username}: {rating}")
            return jsonify({'error': 'Rating must be between 1 and 5'}), 400
        
        rating = int(rating)
        
        # Load existing reviews
        app.logger.debug(f"📂 Loading existing reviews for {name}...")
        reviews_db = safe_read_json(f'reviews/{name}.json', {'reviews': [], 'average': 0})
        
        if not isinstance(reviews_db, dict):
            reviews_db = {'reviews': [], 'average': 0}
        
        existing_reviews = reviews_db.get('reviews', [])
        app.logger.debug(f"📊 Existing reviews: {len(existing_reviews)}")
        
        # Check if user already reviewed this package
        updated = False
        for i, r in enumerate(existing_reviews):
            if r.get('username') == username:
                old_rating = r.get('rating', 0)
                # Update existing review
                existing_reviews[i]['rating'] = rating
                existing_reviews[i]['comment'] = comment
                existing_reviews[i]['updated_at'] = datetime.now().isoformat()
                updated = True
                app.logger.info(f"✏️ Updated existing review by {username} for {name} (rating: {old_rating} → {rating})")
                break
        
        if not updated:
            # Add new review
            new_review = {
                'id': str(uuid.uuid4()),
                'username': username,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            existing_reviews.append(new_review)
            app.logger.info(f"➕ New review by {username} for {name} (rating: {rating})")
        
        reviews_db['reviews'] = existing_reviews
        
        # Recalculate average
        if existing_reviews:
            total = sum(r.get('rating', 0) for r in existing_reviews)
            new_average = round(total / len(existing_reviews), 1)
            reviews_db['average'] = new_average
            app.logger.debug(f"📊 New average rating for {name}: {new_average} ({len(existing_reviews)} reviews)")
        else:
            reviews_db['average'] = 0
            app.logger.debug(f"📊 No reviews for {name}, average reset to 0")
        
        # Save to GitHub
        app.logger.debug(f"💾 Saving reviews to GitHub: reviews/{name}.json")
        save_success = GitHubManager.save_to_github(
            f'reviews/{name}.json',
            reviews_db,
            f"Review by {username} for {name} (rating: {rating})"
        )
        
        if save_success:
            app.logger.info(f"✅ Review saved successfully for {name} by {username}")
        else:
            app.logger.error(f"❌ Failed to save review for {name} to GitHub")
            return jsonify({'error': 'Failed to save review'}), 500
        
        return jsonify({
            'success': True,
            'average': reviews_db['average'],
            'count': len(existing_reviews),
            'updated': updated
        })
    
    except Exception as e:
        app.logger.error(f"❌ Add review error for {name} by {g.user.get('username', 'unknown') if hasattr(g, 'user') else 'unknown'}: {type(e).__name__}: {str(e)}")
        app.logger.debug(f"Stack trace: {e.__traceback__}")
        return jsonify({'error': str(e)}), 500





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
    """Dashboard minimal compatible avec le template"""
    user = g.user
    username = user['username']
    
    try:
        # =====================================================================
        # 1. CHARGER LES PACKAGES DE L'UTILISATEUR
        # =====================================================================
        packages_db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        all_packages = packages_db.get('packages', [])
        
        # Filtrer les packages de l'utilisateur
        user_packages = []
        for pkg in all_packages:
            if pkg.get('author') == username:
                # Créer une copie sécurisée avec toutes les clés nécessaires
                safe_pkg = {
                    'name': pkg.get('name', 'unknown'),
                    'version': pkg.get('version', '0.0.0'),
                    'scope': pkg.get('scope', 'public'),
                    'downloads': pkg.get('downloads', 0),
                    'created_at': pkg.get('created_at'),
                    'size': pkg.get('size', 0),
                    'description': pkg.get('description', '')
                }
                user_packages.append(safe_pkg)
        
        # =====================================================================
        # 2. CALCULER LES STATISTIQUES
        # =====================================================================
        total_packages = len(user_packages)
        total_downloads = sum(p.get('downloads', 0) for p in user_packages)
        
        # Date d'inscription (avec fallback)
        member_since = user.get('created_at', '2026-01-01')
        if member_since and len(member_since) > 10:
            member_since = member_since[:10]
        
        stats = {
            'packages': total_packages,
            'downloads': total_downloads,
            'member_since': member_since
        }
        
        # =====================================================================
        # 3. LOG POUR DÉBOGAGE
        # =====================================================================
        app.logger.info(f"Dashboard loaded for {username}: {total_packages} packages, {total_downloads} downloads")
        
        # =====================================================================
        # 4. RENDU DU TEMPLATE
        # =====================================================================
        return render_template('dashboard.html',
                             user=user,
                             user_packages=user_packages,
                             stats=stats)
    
    except Exception as e:
        app.logger.error(f"Dashboard error for {username}: {str(e)}")
        
        # Statistiques par défaut en cas d'erreur
        default_stats = {
            'packages': 0,
            'downloads': 0,
            'member_since': user.get('created_at', '2026-01-01')[:10] if user.get('created_at') else '2026-01-01'
        }
        
        # Afficher l'erreur à l'utilisateur (optionnel)
        flash('Unable to load some dashboard data', 'warning')
        
        return render_template('dashboard.html',
                             user=user,
                             user_packages=[],
                             stats=default_stats)
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
def community_page():
    """Page communautaire (sans erreur)"""
    try:
        # Charger les données avec des valeurs par défaut
        users_db = GitHubManager.read_from_github('database/users.json', {'users': []})
        packages_db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        
        # Statistiques sécurisées
        total_users = len(users_db.get('users', []))
        total_packages = len(packages_db.get('packages', []))
        
        # Top contributeurs (sans utiliser created_at)
        author_stats = {}
        for pkg in packages_db.get('packages', []):
            author = pkg.get('author')
            if author:
                author_stats[author] = author_stats.get(author, 0) + 1
        
        top_contributors = []
        for author, count in sorted(author_stats.items(), key=lambda x: x[1], reverse=True)[:5]:
            top_contributors.append({
                'username': author,
                'packages': count
            })
        
        return render_template('community.html',
                             total_users=total_users,
                             total_packages=total_packages,
                             online_members=min(total_users, 42),
                             top_contributors=top_contributors,
                             recent_activity=[],
                             forum_categories=[],
                             recent_topics=[],
                             community_badges=[],
                             upcoming_events=[],
                             realtime_stats={},
                             welcome_message="Welcome to the community!",
                             user=session.get('user'))
    
    except Exception as e:
        app.logger.error(f"Community error: {e}")
        return render_template('community.html',
                             total_users=0,
                             total_packages=0,
                             online_members=0,
                             top_contributors=[],
                             recent_activity=[],
                             forum_categories=[],
                             recent_topics=[],
                             community_badges=[],
                             upcoming_events=[],
                             realtime_stats={},
                             welcome_message="Welcome to the community!",
                             user=session.get('user'))
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
@app.route('/badge/<path:badge_name>.<format>')
def serve_badge_svg(badge_name, format='svg'):
    """Générateur de badges avancé avec support des logos, couleurs personnalisées et cache"""
    try:
        # ============================================================================
        # PARSING DE L'URL
        # ============================================================================
        
        # Nettoyer le nom du badge
        if format not in ['svg', 'png', 'json']:
            format = 'svg'
        
        badge_name = badge_name.replace(f'.{format}', '')
        
        # Récupérer les paramètres d'URL (style, logo, etc.)
        style = request.args.get('style', 'flat')  # flat, plastic, for-the-badge, social
        logo = request.args.get('logo', '')
        logo_width = request.args.get('logoWidth', '')
        link = request.args.get('link', '')
        colorA = request.args.get('colorA', '#555')
        colorB = request.args.get('colorB', '')
        label_color = request.args.get('labelColor', '')
        
        # ============================================================================
        # PARSER LE NOM DU BADGE (format: label-value-color)
        # ============================================================================
        
        parts = badge_name.split('-')
        
        if len(parts) >= 3:
            # Format complet: label-value-color
            # Le label peut contenir des tirets, donc on prend le dernier élément comme couleur
            color = parts[-1]
            # La valeur est entre le premier élément et la couleur
            value = '-'.join(parts[1:-1])
            label = parts[0]
        elif len(parts) == 2:
            # Format: label-value (couleur par défaut: blue)
            label, value = parts[0], parts[1]
            color = 'blue'
        else:
            # Format invalide
            label = 'badge'
            value = 'error'
            color = 'red'
        
        # Décoder les caractères URL-encodés
        from urllib.parse import unquote
        label = unquote(label)
        value = unquote(value)
        
        # ============================================================================
        # TABLE DES COULEURS
        # ============================================================================
        
        COLORS = {
            # Couleurs standard
            'blue': '#007ec6',
            'green': '#97ca00',
            'red': '#e05d44',
            'yellow': '#dfb317',
            'orange': '#fe7d37',
            'purple': '#8e44ad',
            'pink': '#ff69b4',
            'gray': '#555555',
            'grey': '#555555',
            'lightgray': '#9f9f9f',
            'lightgrey': '#9f9f9f',
            'white': '#ffffff',
            'black': '#000000',
            
            # Couleurs vives
            'brightgreen': '#4c1',
            'greenyellow': '#a4a61d',
            'yellowgreen': '#a4a61d',
            'yellowgreen': '#a4a61d',
            'orange': '#fe7d37',
            'red': '#e05d44',
            'blue': '#007ec6',
            'cyan': '#00b9fe',
            'magenta': '#f0f',
            
            # Couleurs par nom
            'success': '#4c1',
            'info': '#007ec6',
            'warning': '#dfb317',
            'danger': '#e05d44',
            
            # Couleurs des plateformes
            'discord': '#5865F2',
            'github': '#333333',
            'gitlab': '#fc6d26',
            'docker': '#2496ed',
            'python': '#3776ab',
            'javascript': '#f7df1e',
            'typescript': '#3178c6',
            'rust': '#000000',
            'go': '#00add8',
            'alpine': '#0d597f',
            'linux': '#fcc624',
            'apache': '#d22128',
            'nginx': '#009639',
            'mysql': '#4479a1',
            'postgresql': '#336791',
            'mongodb': '#47a248',
            'redis': '#dc382d',
            'aws': '#ff9900',
            'azure': '#0078d4',
            'gcp': '#4285f4',
            'heroku': '#430098',
            'vercel': '#000000',
            'netlify': '#00c7b7',
        }
        
        # ============================================================================
        # DÉTERMINER LES COULEURS
        # ============================================================================
        
        # Couleur de la partie valeur
        if colorB:
            main_color = colorB
        elif color in COLORS:
            main_color = COLORS[color]
        elif color.startswith('#'):
            main_color = color
        else:
            main_color = COLORS.get(color, '#007ec6')
        
        # Couleur de la partie label
        if label_color:
            label_bg = label_color
        elif colorA:
            label_bg = colorA
        else:
            label_bg = '#555'
        
        # ============================================================================
        # STYLES DE BADGES
        # ============================================================================
        
        # Dimensions de base
        label_padding = 10
        value_padding = 10
        font_size = 11
        char_width = 7  # Largeur approximative par caractère
        
        # Calculer les largeurs
        label_width = max(len(label) * char_width + label_padding, 30)
        value_width = max(len(value) * char_width + value_padding, 30)
        total_width = label_width + value_width
        height = 20
        
        # Ajustements selon le style
        border_radius = 3
        if style == 'plastic':
            height = 22
            font_size = 12
        elif style == 'for-the-badge':
            height = 28
            font_size = 14
            label_padding = 15
            value_padding = 15
            border_radius = 4
        elif style == 'social':
            height = 20
            label_bg = '#f0f0f0'
            main_color = '#f0f0f0'
            font_size = 11
        
        # ============================================================================
        # SUPPORT DES LOGOS (Font Awesome / Simple Icons)
        # ============================================================================
        
        logo_svg = ''
        if logo:
            # Ajuster la largeur pour inclure le logo
            label_padding += 16
            label_width += 16
            
            # Chemins SVG pour les logos populaires
            logos = {
                'github': 'M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z',
                'discord': 'M13.56 2.8C12.45 2.3 11.3 1.9 10.1 1.7c-.1.2-.2.4-.3.6 1.1.2 2.2.6 3.2 1-.9.5-1.9.9-2.9 1.2-.6.2-1.2.4-1.9.5-.2 0-.3.1-.5.1-.6.1-1.3.2-2 .2s-1.4-.1-2-.2c-.2 0-.3-.1-.5-.1-.6-.1-1.3-.3-1.9-.5-1-.3-2-.7-2.9-1.2 1-.4 2-.8 3.2-1-.1-.2-.2-.4-.3-.6-1.2.2-2.4.6-3.5 1.1C1.5 4.3.9 5.6.6 7c1 .5 2.1.9 3.2 1.1.1-.1.1-.2.2-.3.6-1 1.4-1.8 2.4-2.5-.1-.1-.3-.1-.4-.2-.4-.2-.8-.4-1.2-.6.8-.4 1.7-.6 2.6-.7.1 0 .3 0 .4.1.5.2 1 .4 1.5.7.4.2.7.5 1 .8-.1.1-.3.1-.4.2-.3.2-.6.5-.8.7-.1.1-.2.3-.3.4.5-.1 1.1-.1 1.6-.1s1.1 0 1.6.1c-.1-.2-.2-.3-.3-.4-.2-.2-.5-.4-.8-.7-.1-.1-.3-.1-.4-.2.3-.3.6-.6 1-.8.5-.2 1-.5 1.5-.7.1 0 .3 0 .4-.1 1 .1 1.9.3 2.7.6-.4.2-.8.4-1.2.6-.1.1-.3.1-.4.2 1 .7 1.8 1.5 2.4 2.5.1.1.1.2.2.3 1.2-.2 2.3-.5 3.3-1.1-.3-1.4-.9-2.7-1.8-3.8zM5.5 10.2c-.7 0-1.3-.6-1.3-1.4s.6-1.4 1.3-1.4 1.3.6 1.3 1.4-.6 1.4-1.3 1.4zm5 0c-.7 0-1.3-.6-1.3-1.4s.6-1.4 1.3-1.4 1.3.6 1.3 1.4-.6 1.4-1.3 1.4z',
                'docker': 'M1.5 6.5h2v2h-2zm3 0h2v2h-2zm3 0h2v2h-2zm3 0h2v2h-2zm3 0h1v2h-1zm-12 3h2v2h-2zm3 0h2v2h-2zm3 0h2v2h-2zm3 0h2v2h-2zm3-3h1v2h-1z',
                'python': 'M7.5 0C5.5 0 3.5.5 2.5 1.5c-1 1-1.5 3-1.5 5 0 2 1 4 2.5 5 .5.5 1.5 1 2.5 1h5c1 0 2-.5 2.5-1 1.5-1 2.5-3 2.5-5 0-2-.5-4-1.5-5C12.5.5 10.5 0 8.5 0zm0 2h1v1h-1V2zm3 1v1h-1V3h1zM6 4h5c1 0 2 .5 2 1.5V7c0 1-1 1.5-2 1.5H6c-1 0-2-.5-2-1.5V5.5c0-1 1-1.5 2-1.5zm-2 2v1h1V6H4zm6 0v1h1V6h-1z',
                'rust': 'M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z',
            }
            
            if logo in logos:
                logo_svg = f'''<svg x="5" y="2" width="16" height="16" viewBox="0 0 16 16" fill="white">
                    <path d="{logos[logo]}"/>
                </svg>'''
        
        # ============================================================================
        # GÉNÉRATION DU SVG
        # ============================================================================
        
        # Dégradé pour l'effet 3D
        gradient = f'''
        <linearGradient id="smooth" x2="0" y2="100%">
            <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
            <stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>
            <stop offset=".9" stop-color="#000" stop-opacity=".3"/>
            <stop offset="1" stop-color="#000" stop-opacity=".5"/>
        </linearGradient>
        '''
        
        # Badge de base
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" 
            width="{total_width}" height="{height}" role="img" aria-label="{label}: {value}">
            <title>{label}: {value}</title>
            {gradient}
            <rect rx="{border_radius}" width="{total_width}" height="{height}" fill="#555"/>
            <rect rx="{border_radius}" x="{label_width}" width="{value_width}" height="{height}" fill="{main_color}"/>
            <rect rx="{border_radius}" width="{total_width}" height="{height}" fill="url(#smooth)"/>
            {logo_svg}
            <g fill="#fff" text-anchor="middle" font-family="'DejaVu Sans', 'Verdana', 'Geneva', sans-serif" 
                font-size="{font_size}" font-weight="500">
                <text x="{label_width/2 + (16 if logo else 0)}" y="{height - 6}">{label}</text>
                <text x="{label_width + value_width/2}" y="{height - 6}">{value}</text>
            </g>
        </svg>'''
        
        # ============================================================================
        # LIEN HYPERTEXTE (si spécifié)
        # ============================================================================
        
        if link:
            svg = f'''<a href="{link}" target="_blank">
                {svg}
            </a>'''
        
        # ============================================================================
        # FORMAT DE RÉPONSE
        # ============================================================================
        
        # Headers de cache (30 minutes)
        headers = {
            'Cache-Control': 'public, max-age=1800',
            'X-Badge-Generator': 'Zarch-Hub-v5.2',
            'Access-Control-Allow-Origin': '*'
        }
        
        if format == 'json':
            # Retourner les métadonnées du badge au format JSON
            return jsonify({
                'label': label,
                'value': value,
                'color': color,
                'color_hex': main_color,
                'label_color': label_bg,
                'style': style,
                'logo': logo,
                'schemaVersion': 1,
                'labelColor': label_bg,
                'color': main_color,
                'cacheSeconds': 1800
            })
        elif format == 'png':
            # Convertir SVG en PNG (nécessite cairosvg ou autre bibliothèque)
            # Pour l'instant, on redirige vers Shields.io pour le PNG
            return redirect(f'https://img.shields.io/badge/{label}-{value}-{color}.png')
        else:
            # SVG par défaut
            return Response(svg, mimetype='image/svg+xml', headers=headers)
            
    except Exception as e:
        app.logger.error(f"Badge generation error: {e}")
        
        # Badge d'erreur
        error_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">
            <rect rx="3" width="120" height="20" fill="#e05d44"/>
            <g fill="#fff" text-anchor="middle" font-family="sans-serif" font-size="11">
                <text x="60" y="14">error: {str(e)[:20]}</text>
            </g>
        </svg>'''
        
        return Response(error_svg, mimetype='image/svg+xml'), 500






















# FORUM

# ============================================================================
# FORUM - ROUTES PRINCIPALES
# ============================================================================

@app.route('/forum')
def forum_page():
    """Page principale du forum avec catégories et topics"""
    try:
        # Charger les topics depuis GitHub
        forum_db = GitHubManager.read_from_github('forum/topics.json', {
            'topics': [],
            'categories': [
                {'name': 'general', 'label': 'General Discussion', 'icon': 'comments', 'count': 0},
                {'name': 'help', 'label': 'Help & Support', 'icon': 'question-circle', 'count': 0},
                {'name': 'packages', 'label': 'Package Development', 'icon': 'code', 'count': 0},
                {'name': 'goscript', 'label': 'Goscript Language', 'icon': 'microchip', 'count': 0},
                {'name': 'gpm', 'label': 'GPM Package Manager', 'icon': 'box', 'count': 0},
                {'name': 'showcase', 'label': 'Project Showcase', 'icon': 'star', 'count': 0},
                {'name': 'tutorials', 'label': 'Tutorials & Guides', 'icon': 'graduation-cap', 'count': 0},
                {'name': 'feedback', 'label': 'Feedback & Suggestions', 'icon': 'lightbulb', 'count': 0}
            ]
        })

        # Récupérer les paramètres
        page = request.args.get('page', 1, type=int)
        category = request.args.get('category', 'all')
        tag = request.args.get('tag', '')
        sort = request.args.get('sort', 'latest')  # latest, popular, solved
        per_page = 20

        topics = forum_db.get('topics', [])
        categories = forum_db.get('categories', [])

        # Filtrer par catégorie
        if category != 'all':
            topics = [t for t in topics if t.get('category') == category]

        # Filtrer par tag
        if tag:
            topics = [t for t in topics if tag in t.get('tags', [])]

        # Trier
        if sort == 'popular':
            topics.sort(key=lambda x: x.get('views', 0), reverse=True)
        elif sort == 'solved':
            topics.sort(key=lambda x: (not x.get('solved', False), -x.get('views', 0)))
        else:  # latest
            topics.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        # Marquer les topics épinglés en premier
        pinned = [t for t in topics if t.get('pinned')]
        unpinned = [t for t in topics if not t.get('pinned')]
        topics = pinned + unpinned

        # Pagination
        total_topics = len(topics)
        total_pages = max(1, (total_topics + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_topics = topics[start:end]

        # Mettre à jour les compteurs de catégories
        for cat in categories:
            cat['count'] = len([t for t in forum_db.get('topics', []) 
                               if t.get('category') == cat['name']])

        # Statistiques globales
        total_replies = sum(t.get('reply_count', 0) for t in forum_db.get('topics', []))
        total_users = len(set(t.get('author', '') for t in forum_db.get('topics', [])))
        solved_count = len([t for t in forum_db.get('topics', []) if t.get('solved')])

        return render_template('forum.html',
                             topics=paginated_topics,
                             categories=categories,
                             total_topics=total_topics,
                             total_replies=total_replies,
                             total_users=total_users,
                             solved_count=solved_count,
                             current_category=category,
                             current_tag=tag,
                             current_sort=sort,
                             page=page,
                             total_pages=total_pages,
                             now=datetime.now(),
                             user=session.get('user'))

    except Exception as e:
        app.logger.error(f"Forum error: {e}")
        return render_template('forum.html',
                             topics=[],
                             categories=[],
                             total_topics=0,
                             total_replies=0,
                             total_users=0,
                             solved_count=0,
                             current_category='all',
                             current_tag='',
                             current_sort='latest',
                             page=1,
                             total_pages=1,
                             now=datetime.now(),
                             user=session.get('user'))


@app.route('/forum/topic/<slug>')
def forum_topic(slug):
    """Page de détail d'un topic avec ses replies"""
    try:
        forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
        topics = forum_db.get('topics', [])
        
        # Trouver le topic
        topic = next((t for t in topics if t.get('slug') == slug), None)
        
        if not topic:
            abort(404, description="Topic not found")
        
        # Incrémenter les vues
        topic['views'] = topic.get('views', 0) + 1
        GitHubManager.save_to_github('forum/topics.json', forum_db, f"View topic: {slug}")
        
        # Charger les replies
        replies_db = GitHubManager.read_from_github(f'forum/replies/{slug}.json', {'replies': []})
        replies = replies_db.get('replies', [])
        
        # Pagination des replies
        page = request.args.get('page', 1, type=int)
        per_page = 15
        total_replies = len(replies)
        total_pages = max(1, (total_replies + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_replies = replies[start:end]
        
        return render_template('forum_topic.html',
                             topic=topic,
                             replies=paginated_replies,
                             current_page=page,
                             total_pages=total_pages,
                             total_replies=total_replies,
                             now=datetime.now(),
                             user=session.get('user'))
    
    except Exception as e:
        app.logger.error(f"Forum topic error: {e}")
        abort(500)


@app.route('/forum/new', methods=['GET', 'POST'])
def forum_new():
    """Création d'un nouveau topic"""
    if not session.get('user'):
        flash('Please login to create a topic', 'info')
        return redirect('/login?next=/forum/new')
    
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            category = request.form.get('category', '').strip()
            content = request.form.get('content', '').strip()
            tags_raw = request.form.get('tags', '').strip()
            
            # Validation
            if not title or len(title) < 10:
                flash('Title must be at least 10 characters', 'error')
                return render_template('forum_new.html', user=session.get('user'))
            
            if not category:
                flash('Please select a category', 'error')
                return render_template('forum_new.html', user=session.get('user'))
            
            if not content or len(content) < 20:
                flash('Content must be at least 20 characters', 'error')
                return render_template('forum_new.html', user=session.get('user'))
            
            # Parser les tags
            tags = [t.strip().lower().replace(' ', '-')[:30] 
                   for t in tags_raw.split(',') if t.strip()][:5]
            
            # Créer le slug
            slug = re.sub(r'[^a-z0-9-]', '', title.lower().replace(' ', '-'))[:80]
            slug = slug.strip('-')
            
            # Vérifier l'unicité du slug
            forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
            existing_slugs = [t.get('slug') for t in forum_db.get('topics', [])]
            
            if slug in existing_slugs:
                slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            
            # Créer le topic
            new_topic = {
                'id': str(uuid.uuid4()),
                'slug': slug,
                'title': SecurityUtils.escape_text(title),
                'author': session['user']['username'],
                'category': category,
                'content': content,  # Stocké en Markdown
                'tags': tags,
                'views': 0,
                'reply_count': 0,
                'pinned': False,
                'solved': False,
                'locked': False,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'last_reply_at': None,
                'last_reply_by': None
            }
            
            forum_db['topics'].append(new_topic)
            
            if GitHubManager.save_to_github('forum/topics.json', forum_db, 
                                           f"New topic: {title}"):
                flash('Topic created successfully! 🎉', 'success')
                return redirect(f'/forum/topic/{slug}')
            else:
                flash('Failed to create topic. Please try again.', 'error')
                
        except Exception as e:
            app.logger.error(f"Forum new topic error: {e}")
            flash('An error occurred. Please try again.', 'error')
    
    return render_template('forum_new.html', user=session.get('user'))


@app.route('/forum/topic/<slug>/reply', methods=['POST'])
def forum_reply(slug):
    """Ajouter une réponse à un topic"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    try:
        content = request.form.get('content', '').strip()
        
        if not content or len(content) < 10:
            flash('Reply must be at least 10 characters', 'error')
            return redirect(f'/forum/topic/{slug}')
        
        # Vérifier que le topic existe
        forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
        topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
        
        if not topic:
            abort(404)
        
        if topic.get('locked'):
            flash('This topic is locked.', 'error')
            return redirect(f'/forum/topic/{slug}')
        
        # Créer la reply
        new_reply = {
            'id': str(uuid.uuid4()),
            'topic_slug': slug,
            'author': session['user']['username'],
            'content': content,
            'likes': 0,
            'liked_by': [],
            'is_solution': False,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Sauvegarder la reply
        replies_db = GitHubManager.read_from_github(f'forum/replies/{slug}.json', {'replies': []})
        replies_db['replies'].append(new_reply)
        GitHubManager.save_to_github(f'forum/replies/{slug}.json', replies_db, 
                                    f"New reply in: {slug}")
        
        # Mettre à jour le topic
        topic['reply_count'] = len(replies_db['replies'])
        topic['last_reply_at'] = datetime.now().isoformat()
        topic['last_reply_by'] = session['user']['username']
        topic['updated_at'] = datetime.now().isoformat()
        GitHubManager.save_to_github('forum/topics.json', forum_db, f"Update topic: {slug}")
        
        flash('Reply posted successfully!', 'success')
        
    except Exception as e:
        app.logger.error(f"Forum reply error: {e}")
        flash('Failed to post reply.', 'error')
    
    return redirect(f'/forum/topic/{slug}')


@app.route('/forum/topic/<slug>/solution', methods=['POST'])
def forum_mark_solution(slug):
    """Marquer une reply comme solution"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    try:
        data = request.get_json()
        reply_id = data.get('reply_id')
        
        if not reply_id:
            return jsonify({'error': 'reply_id required'}), 400
        
        # Vérifier que le topic existe et que l'utilisateur est l'auteur
        forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
        topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
        
        if not topic:
            return jsonify({'error': 'Topic not found'}), 404
        
        if topic['author'] != session['user']['username']:
            return jsonify({'error': 'Only the topic author can mark a solution'}), 403
        
        # Mettre à jour les replies
        replies_db = GitHubManager.read_from_github(f'forum/replies/{slug}.json', {'replies': []})
        
        for reply in replies_db.get('replies', []):
            if reply['id'] == reply_id:
                reply['is_solution'] = True
            else:
                reply['is_solution'] = False
        
        GitHubManager.save_to_github(f'forum/replies/{slug}.json', replies_db, 
                                    f"Mark solution in: {slug}")
        
        # Marquer le topic comme résolu
        topic['solved'] = True
        GitHubManager.save_to_github('forum/topics.json', forum_db, f"Solved: {slug}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        app.logger.error(f"Mark solution error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/forum/topic/<slug>/like/<reply_id>', methods=['POST'])
def forum_like_reply(slug, reply_id):
    """Liker/Unliker une reply"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    try:
        username = session['user']['username']
        
        replies_db = GitHubManager.read_from_github(f'forum/replies/{slug}.json', {'replies': []})
        
        for reply in replies_db.get('replies', []):
            if reply['id'] == reply_id:
                liked_by = reply.get('liked_by', [])
                
                if username in liked_by:
                    # Unlike
                    liked_by.remove(username)
                    reply['likes'] = max(0, reply.get('likes', 1) - 1)
                    action = 'unliked'
                else:
                    # Like
                    liked_by.append(username)
                    reply['likes'] = reply.get('likes', 0) + 1
                    action = 'liked'
                
                reply['liked_by'] = liked_by
                break
        
        GitHubManager.save_to_github(f'forum/replies/{slug}.json', replies_db, 
                                    f"Like reply in: {slug}")
        
        return jsonify({'success': True, 'action': action})
        
    except Exception as e:
        app.logger.error(f"Like reply error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/forum/topic/<slug>/edit', methods=['GET', 'POST'])
def forum_edit_topic(slug):
    """Éditer un topic (auteur seulement)"""
    if not session.get('user'):
        flash('Please login to edit', 'info')
        return redirect('/login')
    
    forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
    topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
    
    if not topic:
        abort(404)
    
    if topic['author'] != session['user']['username']:
        flash('You can only edit your own topics', 'error')
        return redirect(f'/forum/topic/{slug}')
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        content = request.form.get('content', '').strip()
        tags_raw = request.form.get('tags', '').strip()
        
        if title and len(title) >= 10:
            topic['title'] = SecurityUtils.escape_text(title)
        if category:
            topic['category'] = category
        if content and len(content) >= 20:
            topic['content'] = content
        if tags_raw:
            topic['tags'] = [t.strip().lower().replace(' ', '-')[:30] 
                           for t in tags_raw.split(',') if t.strip()][:5]
        
        topic['updated_at'] = datetime.now().isoformat()
        GitHubManager.save_to_github('forum/topics.json', forum_db, f"Edit topic: {slug}")
        
        flash('Topic updated!', 'success')
        return redirect(f'/forum/topic/{slug}')
    
    return render_template('forum_edit.html', topic=topic, user=session.get('user'))


@app.route('/forum/topic/<slug>/delete', methods=['POST'])
def forum_delete_topic(slug):
    """Supprimer un topic (auteur ou admin)"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
    topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
    
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404
    
    # Vérifier les permissions
    is_author = topic['author'] == session['user']['username']
    is_admin = session['user'].get('role') == 'admin'
    
    if not is_author and not is_admin:
        return jsonify({'error': 'Permission denied'}), 403
    
    # Supprimer le topic
    forum_db['topics'] = [t for t in forum_db['topics'] if t.get('slug') != slug]
    GitHubManager.save_to_github('forum/topics.json', forum_db, f"Delete topic: {slug}")
    
    # Supprimer les replies
    GitHubManager.save_to_github(f'forum/replies/{slug}.json', {'replies': []}, 
                                f"Delete replies for: {slug}")
    
    flash('Topic deleted', 'success')
    return redirect('/forum')


@app.route('/forum/reply/<slug>/<reply_id>/edit', methods=['POST'])
def forum_edit_reply(slug, reply_id):
    """Éditer une reply"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    try:
        content = request.form.get('content', '').strip()
        
        if not content or len(content) < 10:
            return jsonify({'error': 'Reply must be at least 10 characters'}), 400
        
        replies_db = GitHubManager.read_from_github(f'forum/replies/{slug}.json', {'replies': []})
        
        for reply in replies_db.get('replies', []):
            if reply['id'] == reply_id:
                if reply['author'] != session['user']['username']:
                    return jsonify({'error': 'Permission denied'}), 403
                
                reply['content'] = content
                reply['updated_at'] = datetime.now().isoformat()
                break
        
        GitHubManager.save_to_github(f'forum/replies/{slug}.json', replies_db, 
                                    f"Edit reply in: {slug}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/forum/search')
def forum_search():
    """Recherche dans le forum"""
    query = request.args.get('q', '').strip().lower()
    
    if not query or len(query) < 2:
        return redirect('/forum')
    
    forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
    topics = forum_db.get('topics', [])
    
    results = []
    for topic in topics:
        score = 0
        title = topic.get('title', '').lower()
        content = topic.get('content', '').lower()
        tags = ' '.join(topic.get('tags', [])).lower()
        author = topic.get('author', '').lower()
        
        if query in title:
            score += 10
        if query in content:
            score += 5
        if query in tags:
            score += 3
        if query in author:
            score += 2
        
        if score > 0:
            topic['_score'] = score
            results.append(topic)
    
    results.sort(key=lambda x: x.get('_score', 0), reverse=True)
    
    return render_template('forum_search.html',
                         query=query,
                         results=results,
                         total_results=len(results),
                         user=session.get('user'))


@app.route('/forum/topic/<slug>/pin', methods=['POST'])
def forum_pin_topic(slug):
    """Épingler/Désépingler un topic (admin/modérateur)"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    if session['user'].get('role') not in ['admin', 'moderator']:
        return jsonify({'error': 'Permission denied'}), 403
    
    forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
    topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
    
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404
    
    topic['pinned'] = not topic.get('pinned', False)
    GitHubManager.save_to_github('forum/topics.json', forum_db, 
                                f"{'Pin' if topic['pinned'] else 'Unpin'}: {slug}")
    
    return jsonify({'success': True, 'pinned': topic['pinned']})


@app.route('/forum/topic/<slug>/lock', methods=['POST'])
def forum_lock_topic(slug):
    """Verrouiller/Déverrouiller un topic (admin/modérateur)"""
    if not session.get('user'):
        return jsonify({'error': 'Login required'}), 401
    
    if session['user'].get('role') not in ['admin', 'moderator']:
        return jsonify({'error': 'Permission denied'}), 403
    
    forum_db = GitHubManager.read_from_github('forum/topics.json', {'topics': []})
    topic = next((t for t in forum_db.get('topics', []) if t.get('slug') == slug), None)
    
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404
    
    topic['locked'] = not topic.get('locked', False)
    GitHubManager.save_to_github('forum/topics.json', forum_db, 
                                f"{'Lock' if topic['locked'] else 'Unlock'}: {slug}")
    
    return jsonify({'success': True, 'locked': topic['locked']})


# ============================================================================
# FORUM - INITIALISATION
# ============================================================================

def init_forum():
    """Initialise la structure du forum si elle n'existe pas"""
    forum_db = GitHubManager.read_from_github('forum/topics.json', None)
    
    if forum_db is None:
        # Créer la structure initiale
        initial_data = {
            'topics': [
                {
                    'id': str(uuid.uuid4()),
                    'slug': 'welcome-to-zarch-hub-forum',
                    'title': 'Welcome to Zarch Hub Forum!',
                    'author': 'zarch-team',
                    'category': 'general',
                    'content': """# Welcome to the Zarch Hub Forum! 🎉

This is the official community forum for **Goscript** and **GPM**.

## What you can do here:
- 💬 Discuss Goscript language features
- 📦 Share your packages and get feedback
- 🆘 Ask for help with GPM
- 🎯 Showcase your projects
- 💡 Suggest improvements

## Rules:
1. Be respectful and kind
2. Stay on topic
3. No spam or advertising
4. Use appropriate categories
5. Mark solutions when your question is answered

Happy coding! 🚀""",
                    'tags': ['welcome', 'community', 'rules'],
                    'views': 42,
                    'reply_count': 1,
                    'pinned': True,
                    'solved': False,
                    'locked': False,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat(),
                    'last_reply_at': None,
                    'last_reply_by': None
                },
                {
                    'id': str(uuid.uuid4()),
                    'slug': 'goscript-v2-released-whats-new',
                    'title': 'Goscript v2.0 Released - What\'s New',
                    'author': 'gopu-inc',
                    'category': 'goscript',
                    'content': """# Goscript v2.0 is here! 🚀

We're excited to announce the release of Goscript v2.0!

## New Features:
- **Async/Await** - Native async support
- **Struct Inheritance** - `extends` keyword
- **Pattern Matching** - Powerful `match` expressions
- **FFI Improvements** - Better C interop
- **Package Manager** - GPM v1.0

[Read the full changelog](/docs)""",
                    'tags': ['goscript', 'release', 'v2'],
                    'views': 156,
                    'reply_count': 3,
                    'pinned': True,
                    'solved': False,
                    'locked': False,
                    'created_at': (datetime.now() - timedelta(days=2)).isoformat(),
                    'updated_at': (datetime.now() - timedelta(hours=5)).isoformat(),
                    'last_reply_at': (datetime.now() - timedelta(hours=1)).isoformat(),
                    'last_reply_by': 'core_dev'
                }
            ],
            'categories': [
                {'name': 'general', 'label': 'General Discussion', 'icon': 'comments', 'count': 1},
                {'name': 'help', 'label': 'Help & Support', 'icon': 'question-circle', 'count': 0},
                {'name': 'packages', 'label': 'Package Development', 'icon': 'code', 'count': 0},
                {'name': 'goscript', 'label': 'Goscript Language', 'icon': 'microchip', 'count': 1},
                {'name': 'gpm', 'label': 'GPM Package Manager', 'icon': 'box', 'count': 0},
                {'name': 'showcase', 'label': 'Project Showcase', 'icon': 'star', 'count': 0},
                {'name': 'tutorials', 'label': 'Tutorials & Guides', 'icon': 'graduation-cap', 'count': 0},
                {'name': 'feedback', 'label': 'Feedback & Suggestions', 'icon': 'lightbulb', 'count': 0}
            ]
        }
        
        GitHubManager.save_to_github('forum/topics.json', initial_data, 'Init forum')
        
        # Créer la première reply pour le topic de bienvenue
        welcome_replies = {
            'replies': [
                {
                    'id': str(uuid.uuid4()),
                    'topic_slug': 'welcome-to-zarch-hub-forum',
                    'author': 'gopu-inc',
                    'content': 'Welcome everyone! Feel free to introduce yourself in this topic. We\'re excited to have you here! 🎉',
                    'likes': 5,
                    'liked_by': ['zarch-team'],
                    'is_solution': False,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
            ]
        }
        GitHubManager.save_to_github('forum/replies/welcome-to-zarch-hub-forum.json', 
                                    welcome_replies, 'Init welcome replies')
        
        # Mettre à jour le reply_count
        initial_data['topics'][0]['reply_count'] = 1
        GitHubManager.save_to_github('forum/topics.json', initial_data, 'Update reply count')










# ============================================================================
# ROUTE POUR LES BADGES PERSONNALISÉS DES UTILISATEURS
# ============================================================================

@app.route('/badge/custom/<username>/<badge_name>')
def custom_user_badge(username, badge_name):
    """Génère un badge personnalisé créé par un utilisateur"""
    try:
        # Récupérer le badge depuis GitHub
        badges = GitHubManager.read_from_github(f'badges/{username}/badges.json', {})
        badge = badges.get(badge_name.replace('.svg', ''))
        
        if not badge:
            return serve_badge_svg('badge-not_found-red')
        
        # Générer le badge avec les paramètres de l'utilisateur
        return serve_badge_svg(f"{badge['label']}-{badge['value']}-{badge.get('color', 'blue')}")
        
    except Exception as e:
        app.logger.error(f"Custom badge error: {e}")
        return serve_badge_svg('error-server_500-red')


# ============================================================================
# ROUTE POUR LES BADGES DE PACKAGES
# ============================================================================

@app.route('/badge/package/<name>')
def package_badge_redirect(name):
    """Redirige vers Shields.io pour les badges de packages"""
    db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
    package = next((p for p in db.get('packages', []) if p['name'] == name), None)
    
    if not package:
        return serve_badge_svg('package-not_found-red')
    
    # Rediriger vers Shields.io avec les infos du package
    version = package.get('version', 'unknown')
    downloads = package.get('downloads', 0)
    
    return redirect(f'https://img.shields.io/badge/version-{version}-blue')


# ============================================================================
# ENDPOINT POUR LES MÉTADONNÉES DE BADGES (Compatibilité Shields.io)
# ============================================================================

@app.route('/badge/<path:badge_name>/json')
def badge_json_metadata(badge_name):
    """Retourne les métadonnées du badge au format Shields.io"""
    return serve_badge_svg(badge_name, format='json')


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
# ROUTES DE TEST POUR LES COOKIES
# ============================================================================

@app.route('/debug/cookies')
def debug_cookies():
    """Route de debug pour vérifier les cookies"""
    if not app.debug:
        abort(404)
    
    # Récupérer les cookies
    cookies = dict(request.cookies)
    
    # Tenter de déchiffrer le token
    token = CookieManager.get_secure_cookie(request, 'zarch_token')
    
    # Informations sur la session
    session_info = dict(session)
    
    return jsonify({
        'cookies': cookies,
        'has_zarch_token': 'zarch_token' in cookies,
        'decrypted_token': token,
        'session': session_info,
        'user': session.get('user'),
        'fernet_key_configured': bool(SecurityConfig.FERNET_KEY),
        'cookie_secure': app.config.get('SESSION_COOKIE_SECURE'),
        'cookie_samesite': app.config.get('SESSION_COOKIE_SAMESITE')
    })

@app.route('/debug/set-test-cookie')
def debug_set_test_cookie():
    """Route de test pour définir un cookie"""
    if not app.debug:
        abort(404)
    
    response = make_response(jsonify({'message': 'Test cookie set'}))
    
    # Définir un cookie de test
    CookieManager.set_secure_cookie(response, 'test_cookie', 'test_value_123', 3600)
    
    return response

@app.route('/clear-cookies')
def clear_all_cookies():
    """Route temporaire pour forcer la suppression des cookies"""
    response = make_response(redirect('/'))
    
    # Supprimer tous les cookies problématiques
    response.set_cookie('zarch_token', '', expires=0, path='/')
    response.set_cookie('zarch_session', '', expires=0, path='/')
    response.set_cookie('session', '', expires=0, path='/')
    
    # Utiliser votre CookieManager
    CookieManager.delete_secure_cookie(response, 'zarch_token')
    
    # Nettoyer la session
    session.clear()
    
    flash('Cookies nettoyés avec succès ! Veuillez vous reconnecter.', 'success')
    return response
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
    init_forum()
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
