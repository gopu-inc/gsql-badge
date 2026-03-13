#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zarch Package Registry v6.0 - Enterprise Edition
100% GitHub Storage • No Local State • Full Pydantic Validation
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
from typing import Optional, List, Dict, Any, Union
from enum import Enum

# Flask et extensions
from flask import Flask, request, jsonify, g, render_template, make_response, session, redirect, flash, abort
from flask_cors import CORS

# Sécurité avancée
import ssl
import jwt
import bleach
import markupsafe
from markupsafe import escape

# Pydantic v2
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic.networks import EmailStr, HttpUrl

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
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration centrale - Tout vient des variables d'environnement"""
    
    # GitHub
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
    GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/gsql-badge")
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package-data")
    
    # Sécurité
    JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
    APP_SECRET = os.environ.get('APP_SECRET', secrets.token_hex(32))
    
    # Discord OAuth
    DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
    DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
    DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'https://gsql-badge.onrender.com/auth/discord/callback')
    DISCORD_API_ENDPOINT = os.environ.get('DISCORD_API_ENDPOINT', 'https://discord.com/api/v10')
    
    # Paramètres
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB
    TOKEN_EXPIRY_DAYS = int(os.environ.get('TOKEN_EXPIRY_DAYS', 30))
    SESSION_TIMEOUT_HOURS = int(os.environ.get('SESSION_TIMEOUT_HOURS', 24))
    
    # Validation
    REQUIRED_GITHUB_TOKEN: bool = True

# ============================================================================
# MODÈLES PYDANTIC COMPLETS
# ============================================================================

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"
    VERIFIED = "verified"

class PackageScope(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    GLOBAL = "global"

class BadgeStyle(str, Enum):
    FLAT = "flat"
    PLASTIC = "plastic"
    FLAT_SQUARE = "flat-square"
    FOR_THE_BADGE = "for-the-badge"

# ============================================================================
# MODÈLES UTILISATEUR
# ============================================================================

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=30, pattern="^[a-zA-Z0-9_]+$")
    email: EmailStr
    role: UserRole = UserRole.USER
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[HttpUrl] = None
    website: Optional[HttpUrl] = None
    github: Optional[str] = None
    twitter: Optional[str] = None
    discord_id: Optional[str] = None
    discord_username: Optional[str] = None
    discord_avatar: Optional[str] = None
    
    @field_validator('username')
    def validate_username(cls, v):
        forbidden = ['admin', 'root', 'system', 'anonymous', 'null', 'undefined']
        if v.lower() in forbidden:
            raise ValueError(f'Username "{v}" is not allowed')
        return v

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    
    @field_validator('password')
    def validate_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain number')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class UserInDB(UserBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_login: Optional[datetime] = None
    email_verified: bool = False
    email_verification_token: Optional[str] = None
    reset_password_token: Optional[str] = None
    reset_password_expires: Optional[datetime] = None
    discord_token: Optional[str] = None
    discord_refresh_token: Optional[str] = None
    discord_token_expires: Optional[datetime] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================================================================
# MODÈLES PACKAGE
# ============================================================================

class Dependency(BaseModel):
    name: str
    version: str
    optional: bool = False

class PackageMetadata(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern="^\\d+\\.\\d+\\.\\d+$")
    release: str = Field("r0", pattern="^r\\d+$")
    arch: str = Field("x86_64")
    description: Optional[str] = Field(None, max_length=500)
    license: Optional[str] = None
    homepage: Optional[HttpUrl] = None
    repository: Optional[HttpUrl] = None
    keywords: List[str] = Field(default_factory=list)
    dependencies: List[Dependency] = Field(default_factory=list)
    build_dependencies: List[Dependency] = Field(default_factory=list)

class PackageManifest(PackageMetadata):
    maintainer: str
    maintainer_email: Optional[EmailStr] = None
    readme: Optional[str] = None
    changelog: Optional[str] = None
    badges: Dict[str, Any] = Field(default_factory=dict)
    signature: Optional[str] = None
    sha256: Optional[str] = None
    size: Optional[int] = None

class PackageInDB(PackageManifest):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    author_username: str
    scope: PackageScope = PackageScope.PUBLIC
    downloads: int = 0
    stars: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    published_at: Optional[datetime] = None
    verified: bool = False
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    file_sha256: Optional[str] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================================================================
# MODÈLES REVIEW
# ============================================================================

class ReviewBase(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = Field(None, max_length=100)
    comment: Optional[str] = Field(None, max_length=2000)
    pros: Optional[str] = Field(None, max_length=500)
    cons: Optional[str] = Field(None, max_length=500)

class ReviewInDB(ReviewBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    package_id: str
    package_name: str
    author_id: str
    author_username: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    helpful_count: int = 0
    reported: bool = False
    verified_purchase: bool = False
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================================================================
# MODÈLES BADGE
# ============================================================================

class BadgeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, pattern="^[a-z0-9-]+$")
    label: str = Field(..., max_length=30)
    value: str = Field(..., max_length=50)
    color: str = Field("blue", pattern="^(blue|green|red|orange|yellow|purple|pink|gray)$")
    style: BadgeStyle = BadgeStyle.FLAT
    description: Optional[str] = Field(None, max_length=200)

class BadgeInDB(BadgeBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    author_username: str
    created_at: datetime = Field(default_factory=datetime.now)
    usage_count: int = 0
    public: bool = True
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================================================================
# MODÈLES TOKEN
# ============================================================================

class TokenData(BaseModel):
    username: str
    role: UserRole = UserRole.USER
    exp: datetime
    iat: datetime

class TokenInDB(BaseModel):
    token: str
    username: str
    role: UserRole = UserRole.USER
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime
    active: bool = True
    last_used: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

# ============================================================================
# INITIALISATION FLASK
# ============================================================================

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = Config.APP_SECRET
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
app.config['JSON_SORT_KEYS'] = True

# CORS
CORS(app, resources={
    r"/api/*": {"origins": "*"},
    r"/v6/*": {"origins": "*"}
})

# Logging
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
# GITHUB MANAGER (100% STOCKAGE)
# ============================================================================

class GitHubManager:
    """Gestionnaire 100% GitHub - Pas de stockage local"""
    
    @staticmethod
    def get_headers():
        if not Config.GITHUB_TOKEN:
            app.logger.error("GITHUB_TOKEN is not set")
            raise ValueError("GITHUB_TOKEN is required")
        return {
            'Authorization': f'token {Config.GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Zarch-Server/6.0'
        }
    
    @staticmethod
    def get_api_url(path=""):
        return f'https://api.github.com/repos/{Config.GITHUB_REPO}/contents/{path.lstrip("/")}'
    
    @staticmethod
    def read_json(path: str, default: Any = None) -> Any:
        """Lit un fichier JSON depuis GitHub"""
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3.raw'
            
            resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': Config.GITHUB_BRANCH},
                timeout=30
            )
            
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                app.logger.info(f"File not found: {path}, using default")
                return default
                
            app.logger.error(f"GitHub read error {resp.status_code}: {path}")
            return default
            
        except Exception as e:
            app.logger.error(f"GitHub read exception: {e}")
            return default
    
    @staticmethod
    def read_binary(path: str) -> Optional[bytes]:
        """Lit un fichier binaire depuis GitHub"""
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3.raw'
            
            resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': Config.GITHUB_BRANCH},
                timeout=30,
                stream=True
            )
            
            if resp.status_code == 200:
                return resp.content
            return None
            
        except Exception as e:
            app.logger.error(f"Binary read exception: {e}")
            return None
    
    @staticmethod
    def write_json(path: str, data: Any, message: str = "Update") -> bool:
        """Écrit un fichier JSON sur GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            # Récupérer le SHA si le fichier existe
            sha = None
            check_resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': Config.GITHUB_BRANCH}
            )
            if check_resp.status_code == 200:
                sha = check_resp.json().get('sha')
            
            # Préparer le contenu
            content_bytes = json.dumps(data, indent=2, default=str).encode('utf-8')
            
            payload = {
                'message': f'[ZARCH] {message}',
                'content': base64.b64encode(content_bytes).decode('utf-8'),
                'branch': Config.GITHUB_BRANCH
            }
            if sha:
                payload['sha'] = sha
            
            resp = requests.put(
                GitHubManager.get_api_url(path),
                headers=headers,
                json=payload
            )
            
            if resp.status_code in [200, 201]:
                app.logger.info(f"✅ Written to GitHub: {path}")
                return True
            
            app.logger.error(f"❌ Write failed {resp.status_code}: {resp.text}")
            return False
            
        except Exception as e:
            app.logger.error(f"Write exception: {e}")
            return False
    
    @staticmethod
    def write_binary(path: str, data: bytes, message: str = "Upload binary") -> bool:
        """Écrit un fichier binaire sur GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            # Récupérer le SHA si le fichier existe
            sha = None
            check_resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': Config.GITHUB_BRANCH}
            )
            if check_resp.status_code == 200:
                sha = check_resp.json().get('sha')
            
            payload = {
                'message': f'[ZARCH] {message}',
                'content': base64.b64encode(data).decode('utf-8'),
                'branch': Config.GITHUB_BRANCH
            }
            if sha:
                payload['sha'] = sha
            
            resp = requests.put(
                GitHubManager.get_api_url(path),
                headers=headers,
                json=payload
            )
            
            return resp.status_code in [200, 201]
            
        except Exception as e:
            app.logger.error(f"Binary write exception: {e}")
            return False
    
    @staticmethod
    def delete(path: str, message: str = "Delete") -> bool:
        """Supprime un fichier de GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            # Récupérer le SHA
            check_resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': Config.GITHUB_BRANCH}
            )
            if check_resp.status_code != 200:
                return False
            
            sha = check_resp.json().get('sha')
            
            payload = {
                'message': f'[ZARCH] {message}',
                'sha': sha,
                'branch': Config.GITHUB_BRANCH
            }
            
            resp = requests.delete(
                GitHubManager.get_api_url(path),
                headers=headers,
                json=payload
            )
            
            return resp.status_code == 200
            
        except Exception as e:
            app.logger.error(f"Delete exception: {e}")
            return False

# ============================================================================
# GESTIONNAIRES SPÉCIALISÉS
# ============================================================================

class UserManager:
    """Gestionnaire des utilisateurs"""
    
    DB_PATH = "database/users.json"
    
    @classmethod
    def get_all(cls) -> List[UserInDB]:
        data = GitHubManager.read_json(cls.DB_PATH, {'users': []})
        users = []
        for u in data.get('users', []):
            try:
                users.append(UserInDB(**u))
            except Exception as e:
                app.logger.warning(f"Failed to parse user: {e}")
        return users
    
    @classmethod
    def save_all(cls, users: List[UserInDB]) -> bool:
        data = {'users': [u.model_dump(mode='json') for u in users]}
        return GitHubManager.write_json(cls.DB_PATH, data, "Users update")
    
    @classmethod
    def get_by_username(cls, username: str) -> Optional[UserInDB]:
        users = cls.get_all()
        for u in users:
            if u.username == username:
                return u
        return None
    
    @classmethod
    def get_by_email(cls, email: str) -> Optional[UserInDB]:
        users = cls.get_all()
        for u in users:
            if u.email == email:
                return u
        return None
    
    @classmethod
    def get_by_discord_id(cls, discord_id: str) -> Optional[UserInDB]:
        users = cls.get_all()
        for u in users:
            if u.discord_id == discord_id:
                return u
        return None
    
    @classmethod
    def create(cls, user_data: dict) -> Optional[UserInDB]:
        users = cls.get_all()
        
        # Vérifier unicité
        if any(u.username == user_data['username'] for u in users):
            return None
        if any(u.email == user_data['email'] for u in users):
            return None
        
        # Hasher le mot de passe
        if 'password' in user_data:
            password = user_data.pop('password')
            user_data['password_hash'] = bcrypt.hashpw(
                password.encode(), bcrypt.gensalt()
            ).decode()
        
        user = UserInDB(**user_data)
        users.append(user)
        
        if cls.save_all(users):
            return user
        return None
    
    @classmethod
    def update(cls, username: str, updates: dict) -> Optional[UserInDB]:
        users = cls.get_all()
        for i, u in enumerate(users):
            if u.username == username:
                for key, value in updates.items():
                    if hasattr(users[i], key):
                        setattr(users[i], key, value)
                users[i].updated_at = datetime.now()
                if cls.save_all(users):
                    return users[i]
        return None
    
    @classmethod
    def delete(cls, username: str) -> bool:
        users = cls.get_all()
        new_users = [u for u in users if u.username != username]
        if len(new_users) < len(users):
            return cls.save_all(new_users)
        return False
    
    @classmethod
    def verify_password(cls, username: str, password: str) -> bool:
        user = cls.get_by_username(username)
        if not user:
            return False
        return bcrypt.checkpw(password.encode(), user.password_hash.encode())

class PackageManager:
    """Gestionnaire des packages"""
    
    DB_PATH = "database/packages.json"
    
    @classmethod
    def get_all(cls) -> List[PackageInDB]:
        data = GitHubManager.read_json(cls.DB_PATH, {'packages': []})
        packages = []
        for p in data.get('packages', []):
            try:
                packages.append(PackageInDB(**p))
            except Exception as e:
                app.logger.warning(f"Failed to parse package: {e}")
        return packages
    
    @classmethod
    def save_all(cls, packages: List[PackageInDB]) -> bool:
        data = {'packages': [p.model_dump(mode='json') for p in packages]}
        return GitHubManager.write_json(cls.DB_PATH, data, "Packages update")
    
    @classmethod
    def get_by_name(cls, name: str, version: Optional[str] = None) -> Optional[PackageInDB]:
        packages = cls.get_all()
        for p in packages:
            if p.name == name:
                if version is None or p.version == version:
                    return p
        return None
    
    @classmethod
    def get_by_author(cls, author_id: str) -> List[PackageInDB]:
        packages = cls.get_all()
        return [p for p in packages if p.author_id == author_id]
    
    @classmethod
    def search(cls, query: str) -> List[PackageInDB]:
        packages = cls.get_all()
        query = query.lower()
        results = []
        for p in packages:
            if (query in p.name.lower() or 
                (p.description and query in p.description.lower()) or
                query in p.author_username.lower()):
                results.append(p)
        return results
    
    @classmethod
    def create(cls, package_data: dict) -> Optional[PackageInDB]:
        packages = cls.get_all()
        
        # Vérifier si existe déjà
        existing = cls.get_by_name(package_data['name'], package_data['version'])
        if existing:
            return None
        
        package = PackageInDB(**package_data)
        packages.append(package)
        
        if cls.save_all(packages):
            return package
        return None
    
    @classmethod
    def update(cls, package_id: str, updates: dict) -> Optional[PackageInDB]:
        packages = cls.get_all()
        for i, p in enumerate(packages):
            if p.id == package_id:
                for key, value in updates.items():
                    if hasattr(packages[i], key):
                        setattr(packages[i], key, value)
                packages[i].updated_at = datetime.now()
                if cls.save_all(packages):
                    return packages[i]
        return None
    
    @classmethod
    def delete(cls, package_id: str) -> bool:
        packages = cls.get_all()
        new_packages = [p for p in packages if p.id != package_id]
        if len(new_packages) < len(packages):
            return cls.save_all(new_packages)
        return False
    
    @classmethod
    def increment_downloads(cls, name: str, version: str) -> bool:
        packages = cls.get_all()
        for i, p in enumerate(packages):
            if p.name == name and p.version == version:
                packages[i].downloads += 1
                return cls.save_all(packages)
        return False

class ReviewManager:
    """Gestionnaire des reviews"""
    
    @classmethod
    def get_path(cls, package_name: str) -> str:
        return f"reviews/{package_name}.json"
    
    @classmethod
    def get_by_package(cls, package_name: str) -> List[ReviewInDB]:
        data = GitHubManager.read_json(cls.get_path(package_name), {'reviews': []})
        reviews = []
        for r in data.get('reviews', []):
            try:
                reviews.append(ReviewInDB(**r))
            except Exception as e:
                app.logger.warning(f"Failed to parse review: {e}")
        return reviews
    
    @classmethod
    def save_for_package(cls, package_name: str, reviews: List[ReviewInDB]) -> bool:
        data = {'reviews': [r.model_dump(mode='json') for r in reviews]}
        return GitHubManager.write_json(cls.get_path(package_name), data, f"Reviews for {package_name}")
    
    @classmethod
    def add_review(cls, package_name: str, review_data: dict) -> Optional[ReviewInDB]:
        reviews = cls.get_by_package(package_name)
        
        # Vérifier si l'utilisateur a déjà reviewé
        for r in reviews:
            if r.author_id == review_data['author_id']:
                return None
        
        review = ReviewInDB(**review_data)
        reviews.append(review)
        
        if cls.save_for_package(package_name, reviews):
            return review
        return None
    
    @classmethod
    def get_average(cls, package_name: str) -> float:
        reviews = cls.get_by_package(package_name)
        if not reviews:
            return 0.0
        return sum(r.rating for r in reviews) / len(reviews)

class BadgeManager:
    """Gestionnaire des badges personnalisés"""
    
    @classmethod
    def get_path(cls, username: str) -> str:
        return f"badges/{username}/badges.json"
    
    @classmethod
    def get_user_badges(cls, username: str) -> Dict[str, BadgeInDB]:
        data = GitHubManager.read_json(cls.get_path(username), {})
        badges = {}
        for name, b in data.items():
            try:
                badges[name] = BadgeInDB(**b)
            except Exception as e:
                app.logger.warning(f"Failed to parse badge: {e}")
        return badges
    
    @classmethod
    def save_user_badges(cls, username: str, badges: Dict[str, BadgeInDB]) -> bool:
        data = {name: b.model_dump(mode='json') for name, b in badges.items()}
        return GitHubManager.write_json(cls.get_path(username), data, f"Badges for {username}")
    
    @classmethod
    def create_badge(cls, username: str, badge_data: dict) -> Optional[BadgeInDB]:
        badges = cls.get_user_badges(username)
        
        if badge_data['name'] in badges:
            return None
        
        badge = BadgeInDB(**badge_data)
        badges[badge.name] = badge
        
        if cls.save_user_badges(username, badges):
            return badge
        return None
    
    @classmethod
    def increment_usage(cls, username: str, badge_name: str) -> bool:
        badges = cls.get_user_badges(username)
        if badge_name in badges:
            badges[badge_name].usage_count += 1
            return cls.save_user_badges(username, badges)
        return False

class TokenManager:
    """Gestionnaire des tokens JWT (100% GitHub)"""
    
    DB_PATH = "tokens/tokens.json"
    
    @classmethod
    def get_all(cls) -> List[TokenInDB]:
        data = GitHubManager.read_json(cls.DB_PATH, {'tokens': []})
        tokens = []
        for t in data.get('tokens', []):
            try:
                # S'assurer que expires_at existe
                if 'expires_at' not in t:
                    # Token ancien format, lui donner une date par défaut
                    t['expires_at'] = (datetime.now() + timedelta(days=30)).isoformat()
                tokens.append(TokenInDB(**t))
            except Exception as e:
                app.logger.warning(f"Failed to parse token: {e}")
        return tokens
    
    @classmethod
    def save_all(cls, tokens: List[TokenInDB]) -> bool:
        data = {'tokens': [t.model_dump(mode='json') for t in tokens]}
        return GitHubManager.write_json(cls.DB_PATH, data, "Tokens update")
    
    @classmethod
    def create_token(cls, username: str, role: UserRole, user_agent: str = None, ip: str = None) -> Optional[str]:
        """Crée un token JWT et le stocke sur GitHub"""
        tokens = cls.get_all()
        
        # Désactiver les anciens tokens du même utilisateur
        for t in tokens:
            if t.username == username and t.active:
                t.active = False
        
        # Créer le payload JWT
        now = datetime.now()
        expires = now + timedelta(days=Config.TOKEN_EXPIRY_DAYS)
        
        payload = {
            'username': username,
            'role': role.value,
            'iat': int(now.timestamp()),
            'exp': int(expires.timestamp())
        }
        
        token_str = jwt.encode(payload, Config.JWT_SECRET, algorithm='HS256')
        
        # Stocker dans GitHub
        token = TokenInDB(
            token=token_str,
            username=username,
            role=role,
            created_at=now,
            expires_at=expires,
            active=True,
            user_agent=user_agent,
            ip_address=ip
        )
        
        tokens.append(token)
        
        if cls.save_all(tokens):
            return token_str
        return None
    
    @classmethod
    def validate_token(cls, token_str: str) -> Optional[TokenData]:
        """Valide un token"""
        try:
            # Vérifier JWT
            payload = jwt.decode(token_str, Config.JWT_SECRET, algorithms=['HS256'])
            
            # Vérifier dans GitHub
            tokens = cls.get_all()
            for t in tokens:
                if t.token == token_str and t.active:
                    # Vérifier l'expiration
                    if t.expires_at and t.expires_at > datetime.now():
                        # Mettre à jour last_used
                        t.last_used = datetime.now()
                        cls.save_all(tokens)
                        
                        return TokenData(
                            username=payload['username'],
                            role=UserRole(payload['role']),
                            exp=t.expires_at,
                            iat=t.created_at
                        )
            return None
            
        except jwt.ExpiredSignatureError:
            app.logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            app.logger.warning(f"Invalid token: {e}")
            return None
    
    @classmethod
    def revoke_user_tokens(cls, username: str) -> bool:
        """Révoque tous les tokens d'un utilisateur"""
        tokens = cls.get_all()
        for t in tokens:
            if t.username == username:
                t.active = False
        return cls.save_all(tokens)
    
    @classmethod
    def cleanup_expired(cls) -> bool:
        """Nettoie les tokens expirés"""
        tokens = cls.get_all()
        now = datetime.now()
        
        # Garder les tokens actifs non expirés
        active_tokens = []
        for t in tokens:
            if t.active and t.expires_at and t.expires_at > now:
                active_tokens.append(t)
        
        return cls.save_all(active_tokens)

# ============================================================================
# UTILITAIRES DE SÉCURITÉ
# ============================================================================

class SecurityUtils:
    @staticmethod
    def sanitize_html(content: str) -> str:
        return bleach.clean(
            content,
            tags=['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a', 'img'],
            attributes={'a': ['href', 'title'], 'img': ['src', 'alt']},
            strip=True
        )
    
    @staticmethod
    def escape_text(text: str) -> str:
        return escape(str(text))
    
    @staticmethod
    def generate_verification_token() -> str:
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def hash_email(email: str) -> str:
        return hashlib.sha256(email.encode()).hexdigest()

# ============================================================================
# MARKDOWN RENDERER
# ============================================================================

class MarkdownRenderer:
    @staticmethod
    def render(text: str) -> str:
        if not text:
            return "<p>No documentation available.</p>"
        
        extensions = ['extra', 'codehilite', 'toc', 'tables', 'fenced_code']
        html = markdown.markdown(text, extensions=extensions)
        return SecurityUtils.sanitize_html(html)
    
    @staticmethod
    def extract_from_tar(tar_path: str) -> Optional[str]:
        try:
            with tarfile.open(tar_path, 'r:*') as tar:
                # Chercher README
                for member in tar.getmembers():
                    name = member.name.lower()
                    if 'readme' in name and (name.endswith('.md') or name.endswith('.txt')):
                        content = tar.extractfile(member).read().decode('utf-8', errors='ignore')
                        return content
        except Exception as e:
            app.logger.error(f"Error extracting README: {e}")
        return None

# ============================================================================
# DÉCORATEURS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Chercher dans headers
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        token_data = TokenManager.validate_token(token)
        if not token_data:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        g.user = token_data
        return f(*args, **kwargs)
    
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        token_data = TokenManager.validate_token(token)
        if not token_data:
            return jsonify({'error': 'Invalid token'}), 401
        
        if token_data.role != UserRole.ADMIN:
            return jsonify({'error': 'Admin required'}), 403
        
        g.user = token_data
        return f(*args, **kwargs)
    
    return decorated

# ============================================================================
# ROUTES AUTH
# ============================================================================

@app.route('/v6/auth/register', methods=['POST'])
def register():
    """Inscription utilisateur"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        validated = UserCreate(**data)
        
        # Vérifier si l'utilisateur existe déjà
        if UserManager.get_by_username(validated.username):
            return jsonify({'error': 'Username already exists'}), 400
        
        if UserManager.get_by_email(validated.email):
            return jsonify({'error': 'Email already exists'}), 400
        
        # Créer l'utilisateur
        user_data = validated.model_dump()
        user_data['email_verification_token'] = SecurityUtils.generate_verification_token()
        
        user = UserManager.create(user_data)
        if not user:
            return jsonify({'error': 'Failed to create user'}), 500
        
        # Créer token
        token = TokenManager.create_token(
            user.username, 
            user.role,
            request.headers.get('User-Agent'),
            request.remote_addr
        )
        
        if not token:
            return jsonify({'error': 'Failed to create token'}), 500
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'username': user.username,
                'email': user.email,
                'role': user.role.value,
                'created_at': user.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        app.logger.error(f"Register error: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/v6/auth/login', methods=['POST'])
def login():
    """Connexion utilisateur"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        validated = UserLogin(**data)
        
        user = UserManager.get_by_username(validated.username)
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        if not UserManager.verify_password(validated.username, validated.password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Mettre à jour last_login
        UserManager.update(user.username, {'last_login': datetime.now()})
        
        # Créer token
        token = TokenManager.create_token(
            user.username,
            user.role,
            request.headers.get('User-Agent'),
            request.remote_addr
        )
        
        if not token:
            return jsonify({'error': 'Failed to create token'}), 500
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'username': user.username,
                'email': user.email,
                'role': user.role.value,
                'bio': user.bio,
                'avatar': user.avatar_url,
                'created_at': user.created_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        app.logger.error(f"Login error: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/v6/auth/verify', methods=['GET'])
@token_required
def verify_token():
    """Vérifie si le token est valide"""
    return jsonify({
        'valid': True,
        'user': {
            'username': g.user.username,
            'role': g.user.role.value
        }
    }), 200

@app.route('/v6/auth/logout', methods=['POST'])
@token_required
def logout():
    """Déconnexion (révoque le token)"""
    auth_header = request.headers.get('Authorization')
    token = auth_header[7:]
    
    # Révoquer tous les tokens de l'utilisateur
    TokenManager.revoke_user_tokens(g.user.username)
    
    return jsonify({'success': True}), 200

# ============================================================================
# ROUTES PACKAGES
# ============================================================================

@app.route('/v6/packages', methods=['GET'])
def list_packages():
    """Liste tous les packages avec pagination"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    query = request.args.get('q', '').lower()
    scope = request.args.get('scope', 'all')
    
    packages = PackageManager.get_all()
    
    # Filtrer par scope
    if scope != 'all':
        packages = [p for p in packages if p.scope.value == scope]
    
    # Recherche
    if query:
        packages = PackageManager.search(query)
    
    # Pagination
    total = len(packages)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = packages[start:end]
    
    return jsonify({
        'packages': [{
            'name': p.name,
            'version': p.version,
            'release': p.release,
            'arch': p.arch,
            'description': p.description,
            'author': p.author_username,
            'downloads': p.downloads,
            'stars': p.stars,
            'scope': p.scope.value,
            'created_at': p.created_at.isoformat()
        } for p in paginated],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    }), 200

@app.route('/v6/packages/<name>', methods=['GET'])
def get_package(name):
    """Récupère les détails d'un package"""
    version = request.args.get('version')
    
    package = PackageManager.get_by_name(name, version)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    # Chercher le README
    readme = None
    if package.file_path:
        content = GitHubManager.read_binary(package.file_path)
        if content:
            with tempfile.NamedTemporaryFile(suffix='.tar.bool', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            readme_text = MarkdownRenderer.extract_from_tar(tmp_path)
            if readme_text:
                readme = MarkdownRenderer.render(readme_text)
            
            os.unlink(tmp_path)
    
    # Récupérer les reviews
    reviews = ReviewManager.get_by_package(name)
    avg_rating = ReviewManager.get_average(name)
    
    return jsonify({
        'package': package.model_dump(mode='json'),
        'readme': readme,
        'reviews': {
            'count': len(reviews),
            'average': avg_rating,
            'recent': [{
                'author': r.author_username,
                'rating': r.rating,
                'title': r.title,
                'comment': r.comment,
                'created_at': r.created_at.isoformat()
            } for r in reviews[-5:]]
        }
    }), 200

@app.route('/v6/packages', methods=['POST'])
@token_required
def create_package():
    """Crée un nouveau package"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Ajouter les infos d'auteur
        data['author_id'] = g.user.username
        data['author_username'] = g.user.username
        
        package = PackageManager.create(data)
        if not package:
            return jsonify({'error': 'Package already exists'}), 400
        
        return jsonify({
            'success': True,
            'package': package.model_dump(mode='json')
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/v6/packages/<name>/upload', methods=['POST'])
@token_required
def upload_package_file(name):
    """Upload le fichier binaire d'un package"""
    version = request.form.get('version')
    release = request.form.get('release', 'r0')
    arch = request.form.get('arch', 'x86_64')
    
    if not version:
        return jsonify({'error': 'Version is required'}), 400
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.tar.bool'):
        return jsonify({'error': 'Invalid file type, must be .tar.bool'}), 400
    
    # Vérifier que le package existe
    package = PackageManager.get_by_name(name, version)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    # Sauvegarder temporairement
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name
    
    # Lire le contenu
    with open(tmp_path, 'rb') as f:
        content = f.read()
    
    # Calculer SHA256
    sha256 = hashlib.sha256(content).hexdigest()
    size = len(content)
    
    # Chemin GitHub
    filename = f"{name}-{version}-{release}-{arch}.tar.bool"
    github_path = f"packages/{package.scope.value}/{name}/{filename}"
    
    # Upload sur GitHub
    if not GitHubManager.write_binary(github_path, content, f"Upload {name} v{version}"):
        os.unlink(tmp_path)
        return jsonify({'error': 'Upload failed'}), 500
    
    # Mettre à jour le package
    PackageManager.update(package.id, {
        'file_path': github_path,
        'file_size': size,
        'file_sha256': sha256,
        'published_at': datetime.now()
    })
    
    os.unlink(tmp_path)
    
    return jsonify({
        'success': True,
        'sha256': sha256,
        'size': size,
        'path': github_path
    }), 200

@app.route('/v6/packages/<name>/download/<version>/<release>/<arch>', methods=['GET'])
def download_package(name, version, release, arch):
    """Télécharge un package"""
    package = PackageManager.get_by_name(name, version)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    if not package.file_path:
        return jsonify({'error': 'Package file not found'}), 404
    
    # Incrémenter les téléchargements (asynchrone)
    PackageManager.increment_downloads(name, version)
    
    # Récupérer le fichier
    content = GitHubManager.read_binary(package.file_path)
    if not content:
        return jsonify({'error': 'File not found'}), 404
    
    filename = f"{name}-{version}-{release}-{arch}.tar.bool"
    
    response = make_response(content)
    response.headers.set('Content-Type', 'application/gzip')
    response.headers.set('Content-Disposition', f'attachment; filename={filename}')
    response.headers.set('Content-Length', str(len(content)))
    response.headers.set('X-Download-Count', str(package.downloads + 1))
    
    return response

# ============================================================================
# ROUTES REVIEWS
# ============================================================================

@app.route('/v6/packages/<name>/reviews', methods=['GET'])
def get_package_reviews(name):
    """Récupère les reviews d'un package"""
    reviews = ReviewManager.get_by_package(name)
    
    return jsonify({
        'reviews': [{
            'id': r.id,
            'author': r.author_username,
            'rating': r.rating,
            'title': r.title,
            'comment': r.comment,
            'pros': r.pros,
            'cons': r.cons,
            'helpful': r.helpful_count,
            'created_at': r.created_at.isoformat()
        } for r in reviews],
        'average': ReviewManager.get_average(name),
        'total': len(reviews)
    }), 200

@app.route('/v6/packages/<name>/reviews', methods=['POST'])
@token_required
def add_review(name):
    """Ajoute une review à un package"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        package = PackageManager.get_by_name(name)
        if not package:
            return jsonify({'error': 'Package not found'}), 404
        
        review_data = {
            **data,
            'package_id': package.id,
            'package_name': name,
            'author_id': g.user.username,
            'author_username': g.user.username
        }
        
        review = ReviewManager.add_review(name, review_data)
        if not review:
            return jsonify({'error': 'Already reviewed'}), 400
        
        return jsonify({
            'success': True,
            'review': review.model_dump(mode='json')
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ============================================================================
# ROUTES BADGES
# ============================================================================

@app.route('/v6/badges/<username>', methods=['GET'])
def list_user_badges(username):
    """Liste les badges d'un utilisateur"""
    badges = BadgeManager.get_user_badges(username)
    
    return jsonify({
        'badges': [{
            'name': name,
            'label': b.label,
            'value': b.value,
            'color': b.color,
            'style': b.style.value,
            'usage': b.usage_count
        } for name, b in badges.items()]
    }), 200

@app.route('/v6/badges', methods=['POST'])
@token_required
def create_badge():
    """Crée un badge personnalisé"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        data['author_id'] = g.user.username
        data['author_username'] = g.user.username
        
        badge = BadgeManager.create_badge(g.user.username, data)
        if not badge:
            return jsonify({'error': 'Badge already exists'}), 400
        
        return jsonify({
            'success': True,
            'badge': badge.model_dump(mode='json')
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/v6/badges/<username>/<name>/svg', methods=['GET'])
def get_badge_svg(username, name):
    """Génère le SVG d'un badge"""
    badges = BadgeManager.get_user_badges(username)
    badge = badges.get(name)
    
    if not badge:
        return jsonify({'error': 'Badge not found'}), 404
    
    # Incrémenter l'utilisation
    BadgeManager.increment_usage(username, name)
    
    # Générer SVG
    colors = {
        'blue': '#007ec6',
        'green': '#4c1',
        'red': '#e05d44',
        'orange': '#fe7d37',
        'yellow': '#dfb317',
        'purple': '#9f5f9f',
        'pink': '#ff69b4',
        'gray': '#9f9f9f'
    }
    
    hex_color = colors.get(badge.color, colors['blue'])
    
    # Calculer largeurs
    label_len = len(badge.label)
    value_len = len(badge.value)
    label_width = max(label_len * 7 + 10, 30)
    value_width = max(value_len * 7 + 10, 30)
    total_width = label_width + value_width
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img">
        <linearGradient id="s" x2="0" y2="100%">
            <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
            <stop offset="1" stop-opacity=".1"/>
        </linearGradient>
        <clipPath id="r">
            <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
        </clipPath>
        <g clip-path="url(#r)">
            <rect width="{label_width}" height="20" fill="#555"/>
            <rect x="{label_width}" width="{value_width}" height="20" fill="{hex_color}"/>
            <rect width="{total_width}" height="20" fill="url(#s)"/>
        </g>
        <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11">
            <text x="{label_width//2}" y="14">{badge.label}</text>
            <text x="{label_width + value_width//2}" y="14">{badge.value}</text>
        </g>
    </svg>'''
    
    response = make_response(svg)
    response.headers.set('Content-Type', 'image/svg+xml')
    return response

# ============================================================================
# ROUTES UTILISATEURS
# ============================================================================

@app.route('/v6/users/<username>', methods=['GET'])
def get_user_profile(username):
    """Profil public d'un utilisateur"""
    user = UserManager.get_by_username(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    packages = PackageManager.get_by_author(username)
    badges = BadgeManager.get_user_badges(username)
    
    return jsonify({
        'user': {
            'username': user.username,
            'bio': user.bio,
            'avatar': user.avatar_url,
            'website': user.website,
            'github': user.github,
            'twitter': user.twitter,
            'created_at': user.created_at.isoformat()
        },
        'stats': {
            'packages': len(packages),
            'downloads': sum(p.downloads for p in packages),
            'badges': len(badges)
        },
        'packages': [{
            'name': p.name,
            'version': p.version,
            'description': p.description,
            'downloads': p.downloads,
            'stars': p.stars
        } for p in packages[-10:]]
    }), 200

@app.route('/v6/users/<username>/tokens', methods=['DELETE'])
@token_required
def revoke_user_tokens(username):
    """Révoque tous les tokens d'un utilisateur"""
    if g.user.username != username and g.user.role != UserRole.ADMIN:
        return jsonify({'error': 'Unauthorized'}), 403
    
    TokenManager.revoke_user_tokens(username)
    
    return jsonify({'success': True}), 200

# ============================================================================
# ROUTES STATISTIQUES
# ============================================================================

@app.route('/v6/stats', methods=['GET'])
def get_stats():
    """Statistiques globales"""
    packages = PackageManager.get_all()
    users = UserManager.get_all()
    
    total_downloads = sum(p.downloads for p in packages)
    total_stars = sum(p.stars for p in packages)
    
    # Top packages
    top_packages = sorted(packages, key=lambda p: p.downloads, reverse=True)[:10]
    
    # Top contributeurs
    author_stats = {}
    for p in packages:
        author_stats[p.author_username] = author_stats.get(p.author_username, 0) + 1
    
    top_authors = sorted(author_stats.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return jsonify({
        'total_packages': len(packages),
        'total_users': len(users),
        'total_downloads': total_downloads,
        'total_stars': total_stars,
        'top_packages': [{
            'name': p.name,
            'author': p.author_username,
            'downloads': p.downloads
        } for p in top_packages],
        'top_authors': [{
            'username': a,
            'packages': c
        } for a, c in top_authors]
    }), 200

# ============================================================================
# ROUTES WEB
# ============================================================================

@app.route('/')
def index():
    """Page d'accueil"""
    packages = PackageManager.get_all()
    public_packages = [p for p in packages if p.scope == PackageScope.PUBLIC]
    recent = sorted(public_packages, key=lambda p: p.created_at, reverse=True)[:6]
    
    total_downloads = sum(p.downloads for p in packages)
    total_authors = len(set(p.author_username for p in packages))
    
    return render_template('index.html',
                         total_packages=len(packages),
                         total_downloads=total_downloads,
                         total_authors=total_authors,
                         packages=recent,
                         now=datetime.now())

@app.route('/packages')
def packages_page():
    """Page des packages"""
    page = int(request.args.get('page', 1))
    per_page = 12
    query = request.args.get('q', '')
    
    packages = PackageManager.get_all()
    
    if query:
        packages = PackageManager.search(query)
    
    packages = [p for p in packages if p.scope == PackageScope.PUBLIC]
    
    total = len(packages)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = packages[start:end]
    
    return render_template('packages.html',
                         packages=paginated,
                         total_packages=total,
                         total_downloads=sum(p.downloads for p in packages),
                         total_authors=len(set(p.author_username for p in packages)),
                         total_results=total,
                         total_pages=(total + per_page - 1) // per_page,
                         page=page,
                         per_page=per_page,
                         query=query)

@app.route('/package/<name>')
def package_page(name):
    """Page de détail d'un package"""
    version = request.args.get('version')
    
    package = PackageManager.get_by_name(name, version)
    if not package:
        abort(404)
    
    # Lire le README
    readme_html = None
    if package.file_path:
        content = GitHubManager.read_binary(package.file_path)
        if content:
            with tempfile.NamedTemporaryFile(suffix='.tar.bool', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            readme_text = MarkdownRenderer.extract_from_tar(tmp_path)
            if readme_text:
                readme_html = MarkdownRenderer.render(readme_text)
            
            os.unlink(tmp_path)
    
    # Reviews
    reviews = ReviewManager.get_by_package(name)
    avg_rating = ReviewManager.get_average(name)
    
    return render_template('package.html',
                         package=package,
                         readme_html=readme_html,
                         reviews=reviews,
                         avg_rating=avg_rating)

@app.route('/<username>')
def profile_page(username):
    """Page de profil public"""
    user = UserManager.get_by_username(username)
    if not user:
        abort(404)
    
    packages = PackageManager.get_by_author(username)
    badges = BadgeManager.get_user_badges(username)
    
    return render_template('profile.html',
                         profile_user=user,
                         packages=packages,
                         badges=badges)

@app.route('/dashboard')
def dashboard_page():
    """Dashboard utilisateur - accepte token dans header ou URL"""
    token = None
    
    # 1. Chercher dans les headers
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header[7:]
    
    # 2. Chercher dans l'URL (pour les liens directs)
    if not token:
        token = request.args.get('token')
    
    # 3. Chercher dans les cookies (si tu utilises des cookies)
    if not token:
        token = request.cookies.get('zarch_token')
    
    if not token:
        return jsonify({'error': 'Token missing'}), 401
    
    # Valider le token
    user_data = TokenManager.validate_token(token)
    if not user_data:
        return jsonify({'error': 'Invalid or expired token'}), 401
    
    # Récupérer l'utilisateur
    user = UserManager.get_by_username(user_data.username)
    packages = PackageManager.get_by_author(user_data.username)
    badges = BadgeManager.get_user_badges(user_data.username)
    
    return render_template('dashboard.html',
                         user=user,
                         packages=packages,
                         badges=badges)
    
@app.route('/login')
def login_page():
    """Page de connexion"""
    return render_template('login.html')

@app.route('/register')
def register_page():
    """Page d'inscription"""
    return render_template('register.html')

@app.route('/docs')
def docs_page():
    """Page de documentation"""
    return render_template('docs.html')

@app.route('/upload')
@token_required
def upload_page():
    """Page d'upload"""
    return render_template('upload.html')

# ============================================================================
# GESTION DES ERREURS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    app.logger.error(f"500 error: {e}")
    return render_template('500.html'), 500

# ============================================================================
# INITIALISATION
# ============================================================================

def init_github_structure():
    """Initialise la structure de dossiers sur GitHub"""
    app.logger.info("🔧 Initializing GitHub structure...")
    folders = [
        'database',
        'packages/public',
        'packages/private',
        'packages/global',
        'reviews',
        'badges',
        'tokens',
        'forum'
    ]
    
    for folder in folders:
        try:
            # Créer un fichier .gitkeep pour initialiser le dossier
            GitHubManager.write_json(f"{folder}/.gitkeep", {"init": True}, f"Init {folder}")
            app.logger.info(f"  ✅ Created {folder}")
        except Exception as e:
            app.logger.warning(f"  ⚠️  Warning: {folder} - {e}")
    
    app.logger.info("✅ GitHub structure initialized")

# Initialisation au démarrage
with app.app_context():
    try:
        init_github_structure()
        TokenManager.cleanup_expired()
        app.logger.info("🚀 Server initialized successfully")
    except Exception as e:
        app.logger.error(f"Initialization error: {e}")

# ============================================================================
# DÉMARRAGE
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("\n" + "="*60)
    print("🚀 Zarch Server v6.0 - Enterprise Edition")
    print("="*60)
    print(f"📦 GitHub Repo: {Config.GITHUB_REPO}")
    print(f"🌐 Branch: {Config.GITHUB_BRANCH}")
    print(f"🔑 Token expiry: {Config.TOKEN_EXPIRY_DAYS} days")
    print(f"📁 Max upload: {Config.MAX_CONTENT_LENGTH // (1024*1024)}MB")
    print(f"🔗 http://localhost:{port}")
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)
