#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zarch Package Registry v5.4 - Ultimate Edition
Système d'update packages intégré
Sécurité renforcée, API versionnée, Cache intelligent
Stockage GitHub avec gestion de versions
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
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse, urlencode, quote
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

# Flask et extensions
from flask import Flask, request, jsonify, g, render_template, make_response, session, redirect, flash, abort, Response
from flask_cors import CORS

# Sécurité avancée
import ssl
import cryptography
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
import jwt
import bleach
from markupsafe import escape
import pydantic
from pydantic import BaseModel, validator, ValidationError, Field
import semver

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
    
    # GitHub
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', "")
    GITHUB_REPO = os.environ.get('GITHUB_REPO', "gopu-inc/gsql-badge")
    GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME', "gopu-inc")
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', "package-data")
    
    # Paramètres de sécurité
    SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 3600))
    TOKEN_EXPIRY = int(os.environ.get('TOKEN_EXPIRY', 604800))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))
    RATE_LIMIT = int(os.environ.get('RATE_LIMIT', 100))
    COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'False').lower() == 'true'
    COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'Lax')
    
    # Cache
    CACHE_TTL = int(os.environ.get('CACHE_TTL', 300))
    
    # Updates
    UPDATE_CHECK_INTERVAL = int(os.environ.get('UPDATE_CHECK_INTERVAL', 3600))
    MAX_VERSIONS_KEPT = int(os.environ.get('MAX_VERSIONS_KEPT', 5))

# Discord OAuth
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '1467542922139537469')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'https://gsql-badge.onrender.com/auth/discord/callback')
DISCORD_API_ENDPOINT = os.environ.get('DISCORD_API_ENDPOINT', 'https://discord.com/api/v10')
DISCORD_SCOPE = 'identify email guilds'

# ============================================================================
# ENUMS ET TYPES
# ============================================================================

class PackageScope(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    ORGANIZATION = "organization"

class PackageStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    HIDDEN = "hidden"

class UpdateType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    RELEASE = "release"

# ============================================================================
# MODÈLES DE DONNÉES
# ============================================================================

@dataclass
class PackageVersion:
    version: str
    release: str
    arch: str
    sha256: str
    size: int
    created_at: str
    download_url: str
    changelog: Optional[str] = None
    dependencies: List[str] = None
    is_latest: bool = False
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []

@dataclass
class Package:
    name: str
    scope: PackageScope
    author: str
    description: str = ""
    homepage: str = ""
    license: str = "MIT"
    repository: str = ""
    status: PackageStatus = PackageStatus.ACTIVE
    created_at: str = None
    updated_at: str = None
    versions: List[PackageVersion] = None
    downloads: int = 0
    stars: int = 0
    tags: List[str] = None
    
    def __post_init__(self):
        if self.versions is None:
            self.versions = []
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at
    
    def get_latest_version(self) -> Optional[PackageVersion]:
        """Récupère la dernière version selon semver"""
        if not self.versions:
            return None
        
        try:
            return max(self.versions, key=lambda v: semver.VersionInfo.parse(v.version))
        except:
            return sorted(self.versions, key=lambda v: v.created_at, reverse=True)[0]
    
    def get_version(self, version: str, release: str = None, arch: str = None) -> Optional[PackageVersion]:
        """Récupère une version spécifique"""
        for v in self.versions:
            if v.version == version:
                if release and v.release != release:
                    continue
                if arch and v.arch != arch:
                    continue
                return v
        return None
    
    def add_version(self, version: PackageVersion) -> bool:
        """Ajoute une nouvelle version"""
        # Vérifier si la version existe déjà
        existing = self.get_version(version.version, version.release, version.arch)
        if existing:
            return False
        
        self.versions.append(version)
        self.updated_at = datetime.now().isoformat()
        return True
    
    def to_dict(self) -> Dict:
        """Convertit en dictionnaire pour JSON"""
        return {
            'name': self.name,
            'scope': self.scope.value,
            'author': self.author,
            'description': self.description,
            'homepage': self.homepage,
            'license': self.license,
            'repository': self.repository,
            'status': self.status.value,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'downloads': self.downloads,
            'stars': self.stars,
            'tags': self.tags,
            'versions': [asdict(v) for v in self.versions]
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Package':
        """Crée une instance depuis un dictionnaire"""
        data['scope'] = PackageScope(data.get('scope', 'public'))
        data['status'] = PackageStatus(data.get('status', 'active'))
        
        versions = []
        for v in data.get('versions', []):
            versions.append(PackageVersion(**v))
        data['versions'] = versions
        
        return cls(**data)

# ============================================================================
# MODÈLES PYDANTIC (Validation)
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

class PackageCreate(BaseModel):
    name: str
    scope: str = 'public'
    description: str = ""
    homepage: str = ""
    license: str = "MIT"
    repository: str = ""
    tags: List[str] = []
    
    @validator('name')
    def validate_name(cls, v):
        if not v or len(v) < 1:
            raise ValueError('Package name is required')
        if not v.isalnum() and '-' not in v and '_' not in v:
            raise ValueError('Package name can only contain letters, numbers, hyphens and underscores')
        return v.lower()
    
    @validator('scope')
    def validate_scope(cls, v):
        if v not in ['public', 'private', 'organization']:
            raise ValueError('Scope must be public, private, or organization')
        return v

class PackageVersionCreate(BaseModel):
    version: str
    release: str = 'r0'
    arch: str = 'x86_64'
    changelog: str = ""
    dependencies: List[str] = []
    
    @validator('version')
    def validate_version(cls, v):
        try:
            semver.VersionInfo.parse(v)
        except ValueError:
            raise ValueError('Invalid semantic version format')
        return v
    
    @validator('release')
    def validate_release(cls, v):
        if not v.startswith('r') or not v[1:].isdigit():
            raise ValueError('Release must be in format r0, r1, etc.')
        return v
    
    @validator('arch')
    def validate_arch(cls, v):
        valid_archs = ['x86_64', 'arm64', 'armv7', 'i386', 'universal']
        if v not in valid_archs:
            raise ValueError(f'Arch must be one of {valid_archs}')
        return v

class PackageUpdateCheck(BaseModel):
    name: str
    current_version: str
    current_release: str = 'r0'
    arch: str = 'x86_64'

# ============================================================================
# INITIALISATION FLASK
# ============================================================================

app = Flask(__name__, template_folder='templates', static_folder='static')

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

# CORS
CORS(app, resources={
    r"/api/*": {"origins": "*"},
    r"/v5.4/*": {"origins": "*"}
})

# Chiffrement
fernet = Fernet(SecurityConfig.FERNET_KEY.encode())

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
# GESTION DES COOKIES SÉCURISÉS
# ============================================================================

class CookieManager:
    @staticmethod
    def set_secure_cookie(response, name, value, max_age=3600):
        try:
            if not isinstance(value, str):
                value = str(value)
            
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
        except Exception as e:
            app.logger.error(f"Failed to set cookie {name}: {e}")
            return response
    
    @staticmethod
    def get_secure_cookie(request, name):
        encrypted = request.cookies.get(name)
        if not encrypted:
            return None
        
        try:
            encrypted = encrypted.strip()
            decrypted = fernet.decrypt(encrypted.encode()).decode()
            return decrypted
        except Exception:
            return None
    
    @staticmethod
    def delete_secure_cookie(response, name):
        response.set_cookie(name, '', expires=0, path='/')
        return response

# ============================================================================
# CACHE INTELLIGENT
# ============================================================================

class CacheManager:
    _cache = {}
    _ttl = SecurityConfig.CACHE_TTL
    
    @staticmethod
    def get(key):
        data = CacheManager._cache.get(key)
        if data:
            value, timestamp = data
            if time.time() - timestamp < CacheManager._ttl:
                return value
            else:
                del CacheManager._cache[key]
        return None
    
    @staticmethod
    def set(key, value, ttl=None):
        if ttl is None:
            ttl = CacheManager._ttl
        CacheManager._cache[key] = (value, time.time())
    
    @staticmethod
    def invalidate(pattern):
        keys = [k for k in CacheManager._cache.keys() if pattern in k]
        for k in keys:
            del CacheManager._cache[k]
    
    @staticmethod
    def clear():
        CacheManager._cache.clear()

# ============================================================================
# GITHUB MANAGER AMÉLIORÉ
# ============================================================================

class GitHubManager:
    @staticmethod
    def get_headers():
        return {
            'Authorization': f'token {SecurityConfig.GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Zarch-Server/5.4'
        }
    
    @staticmethod
    def get_api_url(path=""):
        return f'https://api.github.com/repos/{SecurityConfig.GITHUB_REPO}/contents/{path.lstrip("/")}'
    
    @staticmethod
    def read_from_github(path, default=None, use_cache=True, binary=False):
        cache_key = f"github:{path}:{binary}"
        if use_cache and not binary:
            cached = CacheManager.get(cache_key)
            if cached is not None:
                return cached
        
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3.raw'
            
            resp = requests.get(
                GitHubManager.get_api_url(path), 
                headers=headers, 
                params={'ref': SecurityConfig.GITHUB_BRANCH},
                timeout=30
            )
            
            if resp.status_code == 200:
                if binary:
                    return resp.content
                
                try:
                    result = json.loads(resp.text)
                except json.JSONDecodeError:
                    result = resp.text
                
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
            
            # Récupérer SHA existant
            sha = None
            check_resp = requests.get(
                GitHubManager.get_api_url(path), 
                headers=headers, 
                params={'ref': SecurityConfig.GITHUB_BRANCH}
            )
            if check_resp.status_code == 200:
                sha = check_resp.json().get('sha')
            
            # Encoder le contenu
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
            if sha:
                data['sha'] = sha
            
            r = requests.put(GitHubManager.get_api_url(path), headers=headers, json=data)
            
            if r.status_code in [200, 201]:
                CacheManager.invalidate(f"github:{path}")
                return True
            
            app.logger.error(f"Save Error {r.status_code}: {r.text}")
            return False
        except Exception as e:
            app.logger.error(f"Save Exception {path}: {e}")
            return False
    
    @staticmethod
    def delete_from_github(path, message="Delete file"):
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3+json'
            
            # Récupérer SHA
            check_resp = requests.get(
                GitHubManager.get_api_url(path), 
                headers=headers, 
                params={'ref': SecurityConfig.GITHUB_BRANCH}
            )
            
            if check_resp.status_code != 200:
                app.logger.warning(f"File not found for deletion: {path}")
                return False
            
            sha = check_resp.json().get('sha')
            
            data = {
                'message': f'[ZARCH] {message}',
                'sha': sha,
                'branch': SecurityConfig.GITHUB_BRANCH
            }
            
            r = requests.delete(GitHubManager.get_api_url(path), headers=headers, json=data)
            
            if r.status_code in [200, 204]:
                CacheManager.invalidate(f"github:{path}")
                return True
            
            app.logger.error(f"Delete Error {r.status_code}: {r.text}")
            return False
            
        except Exception as e:
            app.logger.error(f"Delete Exception {path}: {e}")
            return False
    
    @staticmethod
    def list_directory(path):
        """Liste le contenu d'un répertoire GitHub"""
        try:
            headers = GitHubManager.get_headers()
            headers['Accept'] = 'application/vnd.github.v3+json'
            
            resp = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': SecurityConfig.GITHUB_BRANCH},
                timeout=30
            )
            
            if resp.status_code == 200:
                return resp.json()
            
            return []
        except Exception as e:
            app.logger.error(f"List directory error {path}: {e}")
            return []

# ============================================================================
# GESTIONNAIRE DE PACKAGES
# ============================================================================

class PackageManager:
    PACKAGES_INDEX = 'database/packages/index.json'
    
    @staticmethod
    def get_all_packages() -> Dict[str, Package]:
        """Récupère tous les packages"""
        data = GitHubManager.read_from_github(PackageManager.PACKAGES_INDEX, {'packages': {}})
        
        packages = {}
        for name, pkg_data in data.get('packages', {}).items():
            try:
                packages[name] = Package.from_dict(pkg_data)
            except Exception as e:
                app.logger.error(f"Error loading package {name}: {e}")
        
        return packages
    
    @staticmethod
    def get_package(name: str) -> Optional[Package]:
        """Récupère un package par son nom"""
        packages = PackageManager.get_all_packages()
        return packages.get(name)
    
    @staticmethod
    def save_package(package: Package) -> bool:
        """Sauvegarde un package"""
        packages = PackageManager.get_all_packages()
        packages[package.name] = package
        
        data = {
            'packages': {name: pkg.to_dict() for name, pkg in packages.items()},
            'updated_at': datetime.now().isoformat()
        }
        
        return GitHubManager.save_to_github(
            PackageManager.PACKAGES_INDEX,
            data,
            f"Update package {package.name}"
        )
    
    @staticmethod
    def create_package(author: str, data: PackageCreate) -> Package:
        """Crée un nouveau package"""
        package = Package(
            name=data.name,
            scope=PackageScope(data.scope),
            author=author,
            description=data.description,
            homepage=data.homepage,
            license=data.license,
            repository=data.repository,
            tags=data.tags
        )
        
        # Sauvegarder
        PackageManager.save_package(package)
        
        return package
    
    @staticmethod
    def add_version(
        package_name: str,
        version_data: PackageVersionCreate,
        file_content: bytes,
        author: str
    ) -> Optional[PackageVersion]:
        """Ajoute une version à un package"""
        package = PackageManager.get_package(package_name)
        if not package:
            return None
        
        # Vérifier les permissions
        if package.author != author and author not in ['admin', 'gopu-inc']:
            return None
        
        # Calculer SHA256
        sha256 = hashlib.sha256(file_content).hexdigest()
        
        # Créer la version
        filename = f"{package_name}-{version_data.version}-{version_data.release}-{version_data.arch}.tar.bool"
        pkg_path = f"packages/{package.scope.value}/{package_name}/{filename}"
        
        # Sauvegarder le fichier
        if not GitHubManager.save_to_github(pkg_path, file_content, f"Add {package_name} v{version_data.version}"):
            return None
        
        # Créer l'entrée de version
        version = PackageVersion(
            version=version_data.version,
            release=version_data.release,
            arch=version_data.arch,
            sha256=sha256,
            size=len(file_content),
            created_at=datetime.now().isoformat(),
            download_url=f"/package/download/{package.scope.value}/{package_name}/{version_data.version}/{version_data.release}/{version_data.arch}",
            changelog=version_data.changelog,
            dependencies=version_data.dependencies
        )
        
        # Ajouter au package
        if package.add_version(version):
            # Nettoyer les anciennes versions si nécessaire
            if len(package.versions) > SecurityConfig.MAX_VERSIONS_KEPT:
                # Trier par date et garder les plus récentes
                package.versions.sort(key=lambda v: v.created_at, reverse=True)
                package.versions = package.versions[:SecurityConfig.MAX_VERSIONS_KEPT]
            
            # Marquer la dernière version
            latest = package.get_latest_version()
            for v in package.versions:
                v.is_latest = (v.version == latest.version and 
                              v.release == latest.release and 
                              v.arch == latest.arch)
            
            # Sauvegarder
            PackageManager.save_package(package)
            
            return version
        
        return None
    
    @staticmethod
    def check_for_updates(current: PackageUpdateCheck) -> Dict:
        """Vérifie les mises à jour disponibles"""
        package = PackageManager.get_package(current.name)
        if not package:
            return {'updates_available': False, 'error': 'Package not found'}
        
        latest = package.get_latest_version()
        if not latest:
            return {'updates_available': False}
        
        try:
            current_ver = semver.VersionInfo.parse(current.current_version)
            latest_ver = semver.VersionInfo.parse(latest.version)
            
            updates = []
            
            if latest_ver > current_ver:
                # Déterminer le type de mise à jour
                if latest_ver.major > current_ver.major:
                    update_type = UpdateType.MAJOR
                elif latest_ver.minor > current_ver.minor:
                    update_type = UpdateType.MINOR
                else:
                    update_type = UpdateType.PATCH
                
                # Vérifier si une nouvelle release est disponible pour la même version
                if latest_ver == current_ver and latest.release > current.current_release:
                    update_type = UpdateType.RELEASE
                
                updates.append({
                    'version': latest.version,
                    'release': latest.release,
                    'arch': latest.arch,
                    'type': update_type.value,
                    'changelog': latest.changelog,
                    'size': latest.size,
                    'download_url': latest.download_url,
                    'is_latest': True
                })
            
            # Vérifier les autres versions (pour les mises à jour spécifiques)
            for version in package.versions:
                try:
                    ver = semver.VersionInfo.parse(version.version)
                    if ver > current_ver and version.version != latest.version:
                        updates.append({
                            'version': version.version,
                            'release': version.release,
                            'arch': version.arch,
                            'type': 'intermediate',
                            'changelog': version.changelog,
                            'size': version.size,
                            'download_url': version.download_url,
                            'is_latest': False
                        })
                except:
                    continue
            
            # Trier par version
            updates.sort(key=lambda x: semver.VersionInfo.parse(x['version']), reverse=True)
            
            return {
                'updates_available': len(updates) > 0,
                'current_version': current.current_version,
                'current_release': current.current_release,
                'latest_version': latest.version if latest else None,
                'updates': updates,
                'package_name': package.name,
                'package_author': package.author
            }
            
        except Exception as e:
            app.logger.error(f"Update check error: {e}")
            return {'updates_available': False, 'error': str(e)}
    
    @staticmethod
    def increment_download(package_name: str, version: str, release: str, arch: str):
        """Incrémente le compteur de téléchargements"""
        package = PackageManager.get_package(package_name)
        if not package:
            return
        
        package.downloads += 1
        
        # Trouver la version spécifique (optionnel)
        for v in package.versions:
            if v.version == version and v.release == release and v.arch == arch:
                # On pourrait aussi tracker par version
                pass
        
        PackageManager.save_package(package)
    
    @staticmethod
    def search_packages(query: str, scope: str = None) -> List[Dict]:
        """Recherche des packages"""
        packages = PackageManager.get_all_packages()
        results = []
        
        query = query.lower()
        
        for name, pkg in packages.items():
            # Filtrer par scope
            if scope and scope != 'all' and pkg.scope.value != scope:
                continue
            
            # Ne montrer que les packages actifs
            if pkg.status != PackageStatus.ACTIVE:
                continue
            
            # Calculer le score de pertinence
            score = 0
            
            if query in name.lower():
                score += 10
            if query in pkg.description.lower():
                score += 5
            if query in pkg.author.lower():
                score += 3
            if any(query in tag.lower() for tag in pkg.tags):
                score += 2
            
            if score > 0 or not query:
                latest = pkg.get_latest_version()
                results.append({
                    'name': pkg.name,
                    'scope': pkg.scope.value,
                    'author': pkg.author,
                    'description': pkg.description,
                    'latest_version': latest.version if latest else None,
                    'downloads': pkg.downloads,
                    'stars': pkg.stars,
                    'tags': pkg.tags,
                    'score': score,
                    'url': f"/package/{pkg.name}"
                })
        
        # Trier par score puis par downloads
        results.sort(key=lambda x: (x['score'], x['downloads']), reverse=True)
        
        return results

# ============================================================================
# SÉCURITÉ & AUTH
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
        payload = {
            'username': username,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(seconds=SecurityConfig.TOKEN_EXPIRY)
        }
        return jwt.encode(payload, SecurityConfig.JWT_SECRET, algorithm='HS256')
    
    @staticmethod
    def validate_token(token):
        try:
            payload = jwt.decode(token, SecurityConfig.JWT_SECRET, algorithms=['HS256'])
            return {
                'username': payload.get('username'),
                'role': payload.get('role'),
                'token': token
            }
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def sanitize_html(content):
        return bleach.clean(
            content,
            tags=['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'a', 'img'],
            attributes={'a': ['href', 'title'], 'img': ['src', 'alt']},
            strip=True
        )
    
    @staticmethod
    def escape_text(text):
        return escape(str(text)) if text else ''

# ============================================================================
# MARKDOWN RENDERER
# ============================================================================

class MarkdownRenderer:
    @staticmethod
    def render(text):
        if not text:
            return "<p>No documentation available.</p>"
        
        extensions = ['extra', 'codehilite', 'toc', 'tables', 'fenced_code']
        html = markdown.markdown(text, extensions=extensions)
        html = SecurityUtils.sanitize_html(html)
        
        return f'<div class="markdown-body">{html}</div>'
    
    @staticmethod
    def extract_from_tar(tar_path):
        try:
            with tarfile.open(tar_path, 'r:*') as tar:
                for member in tar.getmembers():
                    name = member.name.lower()
                    if 'readme' in name and (name.endswith('.md') or '.txt' in name):
                        content = tar.extractfile(member).read().decode('utf-8', errors='ignore')
                        return content
        except Exception as e:
            app.logger.error(f"Error extracting README: {e}")
        
        return None

# ============================================================================
# BADGE GENERATOR
# ============================================================================

class BadgeGenerator:
    colors = {
        'blue': '#007ec6',
        'green': '#97ca00',
        'yellow': '#dfb317',
        'red': '#e05d44',
        'orange': '#fe7d37',
        'purple': '#a05dec',
        'pink': '#f07c82',
        'gray': '#555555',
        'lightgray': '#9f9f9f',
        'brightgreen': '#4c1',
        'success': '#4c1',
        'important': '#e05d44',
        'critical': '#e05d44',
        'informational': '#007ec6'
    }
    
    @staticmethod
    def generate(label, value, color="blue"):
        hex_color = BadgeGenerator.colors.get(color.lower(), BadgeGenerator.colors['blue'])
        
        label_width = len(label) * 7 + 10
        value_width = len(str(value)) * 7 + 10
        total_width = label_width + value_width
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
    <linearGradient id="smooth" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity="0.1"/>
        <stop offset="1" stop-opacity="0.1"/>
    </linearGradient>
    <mask id="round">
        <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
    </mask>
    <g mask="url(#round)">
        <rect width="{label_width}" height="20" fill="#555"/>
        <rect x="{label_width}" width="{value_width}" height="20" fill="{hex_color}"/>
        <rect width="{total_width}" height="20" fill="url(#smooth)"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="Verdana" font-size="11">
        <text x="{label_width // 2}" y="14" fill="#010101" fill-opacity="0.3">{escape(label)}</text>
        <text x="{label_width // 2}" y="13">{escape(label)}</text>
        <text x="{label_width + value_width // 2}" y="14" fill="#010101" fill-opacity="0.3">{escape(str(value))}</text>
        <text x="{label_width + value_width // 2}" y="13">{escape(str(value))}</text>
    </g>
</svg>'''
        
        return svg

# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.before_request
def before_request():
    g.request_time = time.time()
    
    # Restaurer session depuis cookie
    if not session.get('user'):
        token = CookieManager.get_secure_cookie(request, 'zarch_token')
        if token:
            user = SecurityUtils.validate_token(token)
            if user:
                session['user'] = user
                session.permanent = True

@app.after_request
def after_request(response):
    # Headers de sécurité
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Temps de réponse
    duration = time.time() - g.request_time
    response.headers['X-Response-Time'] = f'{duration:.3f}s'
    
    return response

# ============================================================================
# DÉCORATEURS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split(" ")
            if len(parts) > 1:
                token = parts[1]
        
        if not token:
            token = CookieManager.get_secure_cookie(request, 'zarch_token')
        
        if not token:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Token missing'}), 401
            flash('Please login to continue', 'info')
            return redirect('/login')
        
        user = SecurityUtils.validate_token(token)
        if not user:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Invalid token'}), 401
            flash('Invalid session, please login again', 'error')
            return redirect('/login')
        
        g.user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.user.get('role') != 'admin' and g.user.get('username') not in ['admin', 'gopu-inc']:
            flash('Admin access required', 'error')
            return redirect('/dashboard')
        return f(*args, **kwargs)
    return decorated

# ============================================================================
# API ROUTES - UPDATE SYSTEM
# ============================================================================

@app.route('/api/v5.4/update/check', methods=['POST'])
def api_check_updates():
    """Vérifie les mises à jour pour un package"""
    try:
        data = request.get_json()
        validated = PackageUpdateCheck(**data)
        
        result = PackageManager.check_for_updates(validated)
        
        return jsonify(result)
        
    except ValidationError as e:
        return jsonify({'error': str(e), 'updates_available': False}), 400
    except Exception as e:
        app.logger.error(f"Update check error: {e}")
        return jsonify({'error': str(e), 'updates_available': False}), 500

@app.route('/api/v5.4/update/bulk', methods=['POST'])
def api_bulk_check_updates():
    """Vérifie les mises à jour pour plusieurs packages"""
    try:
        data = request.get_json()
        packages = data.get('packages', [])
        
        results = {}
        for pkg in packages:
            try:
                validated = PackageUpdateCheck(**pkg)
                results[pkg['name']] = PackageManager.check_for_updates(validated)
            except Exception as e:
                results[pkg['name']] = {
                    'updates_available': False,
                    'error': str(e)
                }
        
        return jsonify({
            'results': results,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        app.logger.error(f"Bulk update check error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/v5.4/package/<name>/versions')
def api_package_versions(name):
    """Liste toutes les versions d'un package"""
    package = PackageManager.get_package(name)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    versions = []
    for v in package.versions:
        versions.append({
            'version': v.version,
            'release': v.release,
            'arch': v.arch,
            'size': v.size,
            'created_at': v.created_at,
            'is_latest': v.is_latest,
            'changelog': v.changelog,
            'download_url': v.download_url
        })
    
    # Trier par version
    try:
        versions.sort(key=lambda x: semver.VersionInfo.parse(x['version']), reverse=True)
    except:
        versions.sort(key=lambda x: x['created_at'], reverse=True)
    
    return jsonify({
        'name': name,
        'versions': versions,
        'total': len(versions)
    })

# ============================================================================
# API ROUTES - PACKAGE MANAGEMENT
# ============================================================================

@app.route('/api/v5.4/package/create', methods=['POST'])
@token_required
def api_create_package():
    """Crée un nouveau package"""
    try:
        data = request.get_json()
        validated = PackageCreate(**data)
        
        # Vérifier si le package existe déjà
        existing = PackageManager.get_package(validated.name)
        if existing:
            return jsonify({'error': 'Package already exists'}), 400
        
        package = PackageManager.create_package(g.user['username'], validated)
        
        return jsonify({
            'success': True,
            'package': package.to_dict()
        })
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        app.logger.error(f"Create package error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/v5.4/package/<name>/add-version', methods=['POST'])
@token_required
def api_add_version(name):
    """Ajoute une version à un package"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        # Récupérer les métadonnées
        version_data = PackageVersionCreate(
            version=request.form.get('version'),
            release=request.form.get('release', 'r0'),
            arch=request.form.get('arch', 'x86_64'),
            changelog=request.form.get('changelog', ''),
            dependencies=json.loads(request.form.get('dependencies', '[]'))
        )
        
        if not file.filename.endswith('.tar.bool'):
            return jsonify({'error': 'Invalid file type, must be .tar.bool'}), 400
        
        # Lire le fichier
        file_content = file.read()
        
        # Ajouter la version
        version = PackageManager.add_version(name, version_data, file_content, g.user['username'])
        
        if not version:
            return jsonify({'error': 'Failed to add version'}), 500
        
        return jsonify({
            'success': True,
            'version': asdict(version)
        })
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        app.logger.error(f"Add version error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/v5.4/package/search')
def api_search_packages():
    """Recherche des packages"""
    query = request.args.get('q', '')
    scope = request.args.get('scope', 'all')
    limit = int(request.args.get('limit', 20))
    
    results = PackageManager.search_packages(query, scope)
    
    return jsonify({
        'results': results[:limit],
        'total': len(results),
        'query': query
    })

@app.route('/api/v5.4/package/<name>')
def api_get_package(name):
    """Récupère les détails d'un package"""
    package = PackageManager.get_package(name)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    return jsonify(package.to_dict())

@app.route('/api/v5.4/package/<name>/stats')
def api_package_stats(name):
    """Statistiques d'un package"""
    package = PackageManager.get_package(name)
    if not package:
        return jsonify({'error': 'Package not found'}), 404
    
    # Statistiques par version
    version_stats = []
    for v in package.versions:
        version_stats.append({
            'version': v.version,
            'release': v.release,
            'arch': v.arch,
            'size': v.size,
            'created_at': v.created_at,
            'is_latest': v.is_latest
        })
    
    return jsonify({
        'name': package.name,
        'author': package.author,
        'total_downloads': package.downloads,
        'total_versions': len(package.versions),
        'latest_version': package.get_latest_version().version if package.versions else None,
        'created_at': package.created_at,
        'updated_at': package.updated_at,
        'version_stats': version_stats
    })

# ============================================================================
# AUTH ROUTES
# ============================================================================

@app.route('/api/v5.4/auth/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        validated = UserLogin(**data)
        
        users = GitHubManager.read_from_github('database/users.json', {'users': []})
        user = next((u for u in users.get('users', []) if u['username'] == validated.username), None)
        
        if user and SecurityUtils.check_password(validated.password, user['password']):
            token = SecurityUtils.generate_token(validated.username, user.get('role', 'user'))
            
            session['user'] = user
            session['token'] = token
            session.permanent = True
            
            response = jsonify({
                'success': True,
                'token': token,
                'user': {
                    'username': user['username'],
                    'role': user.get('role', 'user')
                }
            })
            
            CookieManager.set_secure_cookie(response, 'zarch_token', token, SecurityConfig.TOKEN_EXPIRY)
            
            return response
        
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/v5.4/auth/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        validated = UserRegister(**data)
        
        users = GitHubManager.read_from_github('database/users.json', {'users': []})
        
        if any(u['username'] == validated.username for u in users.get('users', [])):
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
        
        users['users'].append(new_user)
        
        if GitHubManager.save_to_github('database/users.json', users, f"New user: {validated.username}"):
            token = SecurityUtils.generate_token(validated.username)
            
            session['user'] = new_user
            session['token'] = token
            session.permanent = True
            
            response = jsonify({
                'success': True,
                'token': token,
                'user': {
                    'username': validated.username,
                    'role': 'user'
                }
            })
            
            CookieManager.set_secure_cookie(response, 'zarch_token', token, SecurityConfig.TOKEN_EXPIRY)
            
            return response
        
        return jsonify({'error': 'Registration failed'}), 500
        
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/v5.4/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    response = jsonify({'success': True})
    CookieManager.delete_secure_cookie(response, 'zarch_token')
    return response

@app.route('/api/v5.4/auth/me')
@token_required
def api_me():
    return jsonify({
        'user': g.user
    })

# ============================================================================
# WEB ROUTES
# ============================================================================

@app.route('/')
def index():
    packages = PackageManager.get_all_packages()
    
    total_packages = len(packages)
    total_downloads = sum(p.downloads for p in packages.values())
    total_authors = len(set(p.author for p in packages.values()))
    
    # Packages récents
    recent = sorted(
        [p for p in packages.values() if p.scope == PackageScope.PUBLIC],
        key=lambda x: x.created_at,
        reverse=True
    )[:6]
    
    return render_template('index.html',
                         total_packages=total_packages,
                         total_downloads=total_downloads,
                         total_authors=total_authors,
                         packages=recent,
                         now=datetime.now())

@app.route('/packages')
def packages_page():
    page = int(request.args.get('page', 1))
    per_page = 12
    query = request.args.get('q', '')
    sort = request.args.get('sort', 'recent')
    scope = request.args.get('scope', 'all')
    
    results = PackageManager.search_packages(query, scope)
    
    # Tri supplémentaire
    if sort == 'downloads':
        results.sort(key=lambda x: x['downloads'], reverse=True)
    elif sort == 'name':
        results.sort(key=lambda x: x['name'])
    
    total_results = len(results)
    total_pages = (total_results + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    
    paginated = results[start:end]
    
    return render_template('packages.html',
                         packages=paginated,
                         total_results=total_results,
                         total_pages=total_pages,
                         page=page,
                         query=query,
                         sort=sort,
                         scope=scope,
                         now=datetime.now())

@app.route('/package/<name>')
def package_page(name):
    package = PackageManager.get_package(name)
    if not package:
        abort(404)
    
    # Lire le README
    readme_html = None
    latest = package.get_latest_version()
    
    if latest:
        filename = f"{name}-{latest.version}-{latest.release}-{latest.arch}.tar.bool"
        pkg_path = f"packages/{package.scope.value}/{name}/{filename}"
        
        content = GitHubManager.read_from_github(pkg_path, binary=True)
        if content:
            with tempfile.NamedTemporaryFile(suffix='.tar.bool', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                readme_text = MarkdownRenderer.extract_from_tar(tmp_path)
                if readme_text:
                    readme_html = MarkdownRenderer.render(readme_text)
            finally:
                os.unlink(tmp_path)
    
    return render_template('package.html',
                         package=package,
                         readme_html=readme_html,
                         now=datetime.now())

@app.route('/package/download/<scope>/<name>/<version>/<release>/<arch>')
def download_package(scope, name, version, release, arch):
    filename = f"{name}-{version}-{release}-{arch}.tar.bool"
    pkg_path = f"packages/{scope}/{name}/{filename}"
    
    app.logger.info(f"Download: {pkg_path}")
    
    content = GitHubManager.read_from_github(pkg_path, binary=True)
    if not content:
        abort(404)
    
    # Incrémenter les téléchargements en arrière-plan
    def update_downloads():
        try:
            PackageManager.increment_download(name, version, release, arch)
        except Exception as e:
            app.logger.error(f"Failed to update downloads: {e}")
    
    thread = threading.Thread(target=update_downloads)
    thread.daemon = True
    thread.start()
    
    response = make_response(content)
    response.headers.set('Content-Type', 'application/gzip')
    response.headers.set('Content-Disposition', f'attachment; filename={filename}')
    response.headers.set('Content-Length', str(len(content)))
    
    return response

@app.route('/dashboard')
@token_required
def dashboard_page():
    user = g.user
    username = user['username']
    
    packages = PackageManager.get_all_packages()
    user_packages = [p for p in packages.values() if p.author == username]
    
    stats = {
        'total_packages': len(user_packages),
        'total_downloads': sum(p.downloads for p in user_packages),
        'total_versions': sum(len(p.versions) for p in user_packages)
    }
    
    # Données pour les graphiques
    chart_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
    
    if stats['total_downloads'] > 0:
        chart_data = [
            int(stats['total_downloads'] * 0.1),
            int(stats['total_downloads'] * 0.15),
            int(stats['total_downloads'] * 0.2),
            int(stats['total_downloads'] * 0.25),
            int(stats['total_downloads'] * 0.2),
            int(stats['total_downloads'] * 0.1)
        ]
    else:
        chart_data = [0, 0, 0, 0, 0, 0]
    
    return render_template('dashboard.html',
                         user=user,
                         user_packages=user_packages,
                         stats=stats,
                         chart_labels=chart_labels,
                         chart_data=chart_data,
                         now=datetime.now())

@app.route('/upload')
@token_required
def upload_page():
    return render_template('upload.html', user=g.user)

@app.route('/login')
def login_page():
    if session.get('user'):
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/register')
def register_page():
    if session.get('user'):
        return redirect('/dashboard')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    response = make_response(redirect('/'))
    CookieManager.delete_secure_cookie(response, 'zarch_token')
    flash('Logged out successfully', 'success')
    return response

@app.route('/docs')
def docs_page():
    return render_template('docs.html')

@app.route('/stats')
def stats_page():
    packages = PackageManager.get_all_packages()
    
    stats = {
        'total_packages': len(packages),
        'total_downloads': sum(p.downloads for p in packages.values()),
        'total_authors': len(set(p.author for p in packages.values())),
        'public_packages': len([p for p in packages.values() if p.scope == PackageScope.PUBLIC]),
        'private_packages': len([p for p in packages.values() if p.scope == PackageScope.PRIVATE]),
        'total_versions': sum(len(p.versions) for p in packages.values())
    }
    
    return render_template('stats.html', stats=stats)

# ============================================================================
# BADGES
# ============================================================================

@app.route('/badge/<path:badge_name>')
def serve_badge(badge_name):
    parts = badge_name.replace('.svg', '').split('-')
    
    if len(parts) >= 2:
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
    package = PackageManager.get_package(name)
    if not package:
        return serve_badge('package-not_found-red')
    
    latest = package.get_latest_version()
    version = latest.version if latest else 'unknown'
    
    svg = BadgeGenerator.generate('version', version, 'blue')
    return Response(svg, mimetype='image/svg+xml')

@app.route('/badge/package/<name>/downloads')
def package_downloads_badge(name):
    package = PackageManager.get_package(name)
    if not package:
        return serve_badge('package-not_found-red')
    
    downloads = package.downloads
    svg = BadgeGenerator.generate('downloads', f"{downloads}", 'green')
    return Response(svg, mimetype='image/svg+xml')

@app.route('/badge/package/<name>/license')
def package_license_badge(name):
    package = PackageManager.get_package(name)
    if not package:
        return serve_badge('package-not_found-red')
    
    license_name = package.license
    svg = BadgeGenerator.generate('license', license_name, 'yellow')
    return Response(svg, mimetype='image/svg+xml')

# ============================================================================
# INSTALL SCRIPT
# ============================================================================

@app.route('/install.sh')
def install_script():
    script = """#!/bin/sh
# Zarch Hub Auto-Installer v5.4
set -e

echo "🚀 Zarch Hub Installer v5.4"
echo "==========================="

# Colors
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m'

# Check root
if [ "$EUID" -ne 0 ]; then 
    echo "${RED}❌ Please run as root${NC}"
    exit 1
fi

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)  ARCH="x86_64" ;;
    aarch64) ARCH="arm64" ;;
    armv7l)  ARCH="armv7" ;;
    *)       echo "${RED}❌ Unsupported architecture: $ARCH${NC}"; exit 1 ;;
esac

echo "${YELLOW}🔧 Architecture: $ARCH${NC}"

# Base URL
BASE_URL="https://gsql-badge.onrender.com"

# Install APKM
echo "${BLUE}📦 Installing APKM...${NC}"
curl -L -o /tmp/apkm.tar.bool "$BASE_URL/package/download/public/apkm/2.0.0/r1/$ARCH"
tar -xf /tmp/apkm.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xzf /tmp/apkm.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/apkm
rm -f /tmp/apkm.tar.bool

# Install APSM
echo "${BLUE}📦 Installing APSM...${NC}"
curl -L -o /tmp/apsm.tar.bool "$BASE_URL/package/download/public/apsm/2.0.0/r1/$ARCH"
tar -xf /tmp/apsm.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xzf /tmp/apsm.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/apsm
rm -f /tmp/apsm.tar.bool

# Install BOOL
echo "${BLUE}📦 Installing BOOL...${NC}"
curl -L -o /tmp/bool.tar.bool "$BASE_URL/package/download/public/bool/2.0.0/r1/$ARCH"
tar -xf /tmp/bool.tar.bool -C /usr/local/bin/ 2>/dev/null || tar -xzf /tmp/bool.tar.bool -C /usr/local/bin/
chmod +x /usr/local/bin/bool
rm -f /tmp/bool.tar.bool

# Create directories
mkdir -p /usr/local/share/apkm/{database,cache,PROTOCOLE/security/tokens}

# Configure repositories
echo "${BLUE}⚙️  Configuring APKM...${NC}"
cat > /etc/apkm/repositories.conf << EOF
# APKM Repositories
zarch-hub https://gsql-badge.onrender.com 5
EOF

# Verify installation
echo "${GREEN}✅ Installation complete!${NC}"
echo ""
echo "📋 Commands installed:"
echo "   $(which apkm) - Package manager"
echo "   $(which apsm) - Package publisher"
echo "   $(which bool) - Package builder"
echo ""
echo "🚀 Try: apkm --help"
echo "🔐 Login: apsm login"
echo "🏗️  Build: bool --verify"
echo ""
echo "${YELLOW}📊 Version info:${NC}"
apkm --version
"""
    
    return Response(script, mimetype='text/plain', headers={
        'Content-Disposition': 'attachment; filename="install.sh"',
        'Cache-Control': 'no-cache'
    })

# ============================================================================
# DEBUG ROUTES
# ============================================================================

@app.route('/debug/status')
def debug_status():
    if not app.debug:
        abort(404)
    
    packages = PackageManager.get_all_packages()
    
    return jsonify({
        'status': 'ok',
        'version': '5.4',
        'packages': len(packages),
        'cache_size': len(CacheManager._cache),
        'session': dict(session) if session else None,
        'time': datetime.now().isoformat()
    })

@app.route('/debug/cache/clear', methods=['POST'])
def debug_cache_clear():
    if not app.debug:
        abort(404)
    
    CacheManager.clear()
    return jsonify({'success': True, 'message': 'Cache cleared'})

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"500 error: {e}")
    return render_template('500.html'), 500

# ============================================================================
# INITIALIZATION
# ============================================================================

def init_storage():
    """Initialise le stockage"""
    os.makedirs('/tmp/zarch_uploads', exist_ok=True)
    os.makedirs('/tmp/zarch_temp', exist_ok=True)
    
    # Créer l'index des packages s'il n'existe pas
    if not GitHubManager.read_from_github(PackageManager.PACKAGES_INDEX):
        GitHubManager.save_to_github(
            PackageManager.PACKAGES_INDEX,
            {
                'packages': {},
                'created_at': datetime.now().isoformat(),
                'version': '5.4'
            },
            'Initialize package index'
        )
    
    # Créer la base utilisateurs si nécessaire
    if not GitHubManager.read_from_github('database/users.json'):
        GitHubManager.save_to_github(
            'database/users.json',
            {'users': [], 'created_at': datetime.now().isoformat()},
            'Initialize users database'
        )

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    init_storage()
    
    print("🚀 Zarch Server v5.4 - Ultimate Edition")
    print("=" * 60)
    print(f"📦 GitHub Repo: {SecurityConfig.GITHUB_REPO}")
    print(f"🔒 Session timeout: {SecurityConfig.SESSION_TIMEOUT}s")
    print(f"🔑 Token expiry: {SecurityConfig.TOKEN_EXPIRY}s")
    print(f"📁 Max upload: {SecurityConfig.MAX_CONTENT_LENGTH // (1024*1024)}MB")
    print(f"🔄 Update check interval: {SecurityConfig.UPDATE_CHECK_INTERVAL}s")
    print(f"📚 Max versions kept: {SecurityConfig.MAX_VERSIONS_KEPT}")
    print(f"🌐 API version: /v5.4/")
    print(f"🔗 http://localhost:10000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
