"""
Zenv Package Hub - Version complète avec support token zenv_
Stockage direct GitHub branch package-data
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
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response, g
from flask_cors import CORS

# ============================================================================
# CONFIGURATION GITHUB - BRANCH PACKAGE-DATA
# ============================================================================

# Configuration GitHub - TOKEN DIRECT
GITHUB_TOKEN = "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"
GITHUB_REPO = "gopu-inc/zenv"
GITHUB_USERNAME = "gopu-inc"
GITHUB_EMAIL = "ceoseshell@gmail.com"
GITHUB_BRANCH = "package-data"

# Configuration JWT
JWT_SECRET = "zenv_hub_permanent_token_secret_2024"
APP_SECRET = "zenv_app_secret_2024"

# TOKEN PRÉ-EXISTANT POUR TESTS
PREDEFINED_TOKENS = {
    "zenv_ead27bf9d1b91e30729eb574a82e7287d4c9f35df9f8feb4f581452444350a5b": {
        "user_id": "1",
        "username": "admin",
        "role": "admin",
        "created_at": "2024-01-01T00:00:00"
    }
}

# Initialisation Flask
app = Flask(__name__)
CORS(app)

app.config.update(
    SECRET_KEY=APP_SECRET,
    JWT_SECRET_KEY=JWT_SECRET,
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    JWT_ACCESS_TOKEN_EXPIRES=3153600000,  # 100 ans
    BCRYPT_ROUNDS=12
)

# ============================================================================
# GESTIONNAIRE GITHUB DIRECT
# ============================================================================

class GitHubManager:
    """Gestionnaire de stockage direct sur GitHub"""
    
    @staticmethod
    def get_headers():
        return {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
    
    @staticmethod
    def get_api_url(path=""):
        return f'https://api.github.com/repos/{GITHUB_REPO}/contents/{path.lstrip("/")}'
    
    @staticmethod
    def get_raw_url(path=""):
        return f'https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path.lstrip("/")}'
    
    @staticmethod
    def init_github_repo():
        """Initialiser le dépôt GitHub"""
        try:
            print(f"🚀 Initialisation GitHub: {GITHUB_REPO}:{GITHUB_BRANCH}")
            
            headers = GitHubManager.get_headers()
            
            # Vérifier la branche
            response = requests.get(
                f'https://api.github.com/repos/{GITHUB_REPO}/branches/{GITHUB_BRANCH}',
                headers=headers
            )
            
            if response.status_code != 200:
                print(f"⚠️ Branche '{GITHUB_BRANCH}' non trouvée")
                return False
            
            # Vérifier/Créer la structure
            folders = ['database', 'packages', 'badges', 'tokens']
            
            for folder in folders:
                try:
                    response = requests.get(
                        GitHubManager.get_api_url(folder),
                        headers=headers,
                        params={'ref': GITHUB_BRANCH}
                    )
                    
                    if response.status_code != 200:
                        # Créer le dossier
                        data = {
                            'message': f'Create {folder} directory',
                            'content': base64.b64encode(b'{}').decode('utf-8'),
                            'branch': GITHUB_BRANCH
                        }
                        
                        response = requests.put(
                            GitHubManager.get_api_url(f'{folder}/.gitkeep'),
                            headers=headers,
                            json=data
                        )
                        
                        if response.status_code in [200, 201]:
                            print(f"✅ Dossier créé: {folder}/")
                except:
                    pass
            
            # Initialiser la base de données
            db_path = 'database/zenv_hub.json'
            db = GitHubManager.read_from_github(db_path)
            
            if db is None:
                initial_db = {
                    'users': [
                        {
                            'id': '1',
                            'username': 'admin',
                            'email': 'admin@zenvhub.com',
                            'password': bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode(),
                            'role': 'admin',
                            'created_at': datetime.now().isoformat(),
                            'is_verified': True
                        }
                    ],
                    'packages': [],
                    'badges': [],
                    'stats': {
                        'total_packages': 0,
                        'total_downloads': 0,
                        'total_users': 1,
                        'total_badges': 0
                    }
                }
                
                GitHubManager.save_to_github(db_path, initial_db, 'Initialize database')
                print("✅ Base de données initialisée")
            
            print(f"🎉 GitHub initialisé avec succès!")
            return True
            
        except Exception as e:
            print(f"❌ Erreur initialisation GitHub: {e}")
            return False
    
    @staticmethod
    def save_to_github(path, content, message="Auto save"):
        """Sauvegarder sur GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            # Vérifier si le fichier existe
            response = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': GITHUB_BRANCH}
            )
            
            sha = None
            if response.status_code == 200:
                sha = response.json().get('sha')
            
            # Préparer le contenu
            if isinstance(content, str):
                content_bytes = content.encode('utf-8')
            elif isinstance(content, (dict, list)):
                content_bytes = json.dumps(content, indent=2).encode('utf-8')
            else:
                content_bytes = content
            
            content_b64 = base64.b64encode(content_bytes).decode('utf-8')
            
            data = {
                'message': f'[Zenv Hub] {message}',
                'content': content_b64,
                'branch': GITHUB_BRANCH
            }
            
            if sha:
                data['sha'] = sha
            
            response = requests.put(
                GitHubManager.get_api_url(path),
                headers=headers,
                json=data
            )
            
            return response.status_code in [200, 201]
                
        except Exception as e:
            print(f"❌ Erreur save_to_github: {e}")
            return False
    
    @staticmethod
    def read_from_github(path, default=None):
        """Lire depuis GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            response = requests.get(
                GitHubManager.get_api_url(path),
                headers=headers,
                params={'ref': GITHUB_BRANCH}
            )
            
            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                
                try:
                    return json.loads(content)
                except:
                    return content
            
            return default
                
        except Exception as e:
            print(f"❌ Erreur read_from_github: {e}")
            return default
    
    @staticmethod
    def upload_package(file_obj, package_name, version):
        """Uploader un package sur GitHub"""
        try:
            # Créer répertoire temporaire
            temp_dir = tempfile.mkdtemp()
            filename = f"{package_name}-{version}.zv"
            temp_path = os.path.join(temp_dir, filename)
            
            # Sauvegarder temporairement
            file_obj.save(temp_path)
            
            # Lire le fichier
            with open(temp_path, 'rb') as f:
                content = f.read()
            
            # Chemin GitHub
            github_path = f"packages/{package_name}/{filename}"
            
            headers = GitHubManager.get_headers()
            content_b64 = base64.b64encode(content).decode('utf-8')
            
            # Vérifier si existe
            response = requests.get(
                GitHubManager.get_api_url(github_path),
                headers=headers,
                params={'ref': GITHUB_BRANCH}
            )
            
            sha = None
            if response.status_code == 200:
                sha = response.json().get('sha')
            
            data = {
                'message': f'Upload package {package_name} v{version}',
                'content': content_b64,
                'branch': GITHUB_BRANCH
            }
            
            if sha:
                data['sha'] = sha
            
            response = requests.put(
                GitHubManager.get_api_url(github_path),
                headers=headers,
                json=data
            )
            
            # Nettoyer
            shutil.rmtree(temp_dir)
            
            if response.status_code in [200, 201]:
                download_url = GitHubManager.get_raw_url(github_path)
                return True, download_url, len(content)
            else:
                return False, None, 0
                
        except Exception as e:
            print(f"❌ Erreur upload_package: {e}")
            return False, None, 0
    
    @staticmethod
    def list_packages():
        """Lister les packages depuis GitHub"""
        try:
            headers = GitHubManager.get_headers()
            
            # Liste des packages dans le dépôt
            response = requests.get(
                GitHubManager.get_api_url('packages'),
                headers=headers,
                params={'ref': GITHUB_BRANCH}
            )
            
            if response.status_code != 200:
                return []
            
            packages = []
            items = response.json()
            
            for item in items:
                if item['type'] == 'dir':
                    package_name = item['name']
                    
                    # Lire les fichiers du package
                    files_resp = requests.get(item['url'], headers=headers)
                    if files_resp.status_code == 200:
                        files = files_resp.json()
                        for file in files:
                            if file['type'] == 'file':
                                # Extraire la version
                                filename = file['name']
                                match = re.search(r'(.+)-(\d+\.\d+\.\d+.*?)\.', filename)
                                
                                version = '1.0.0'
                                if match:
                                    version = match.group(2)
                                
                                packages.append({
                                    'name': package_name,
                                    'version': version,
                                    'filename': filename,
                                    'size': file.get('size', 0),
                                    'download_url': GitHubManager.get_raw_url(file['path']),
                                    'updated_at': datetime.now().isoformat()
                                })
            
            return packages
                
        except Exception as e:
            print(f"❌ Erreur list_packages: {e}")
            return []
    
    @staticmethod
    def download_package(package_name, filename):
        """Télécharger un package depuis GitHub"""
        try:
            github_path = f"packages/{package_name}/{filename}"
            raw_url = GitHubManager.get_raw_url(github_path)
            
            response = requests.get(raw_url)
            if response.status_code == 200:
                return response.content
            else:
                return None
                
        except Exception as e:
            print(f"❌ Erreur download_package: {e}")
            return None

# ============================================================================
# UTILITAIRES DE SÉCURITÉ
# ============================================================================

class SecurityUtils:
    """Utilitaires de sécurité avec support token zenv_"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except:
            return False
    
    @staticmethod
    def verify_token(token: str):
        """Vérifier un token (support zenv_ format)"""
        try:
            # Vérifier les tokens prédéfinis
            if token in PREDEFINED_TOKENS:
                return PREDEFINED_TOKENS[token]
            
            # Vérifier format zenv_
            if token.startswith('zenv_'):
                # Vérifier dans la base de données GitHub
                tokens_db = GitHubManager.read_from_github('tokens/tokens.json', {'tokens': []})
                
                for token_info in tokens_db.get('tokens', []):
                    if token_info.get('token') == token:
                        if not token_info.get('active', True):
                            raise Exception("Token désactivé")
                        
                        return {
                            'user_id': token_info.get('user_id', '1'),
                            'username': token_info.get('username', 'user'),
                            'role': token_info.get('role', 'user')
                        }
                
                # Si token zenv_ non trouvé mais valide, accepter
                if len(token) > 50:  # Token semble valide
                    print(f"⚠️ Token zenv_ non enregistré mais accepté: {token[:20]}...")
                    return {
                        'user_id': '1',
                        'username': 'cli_user',
                        'role': 'user'
                    }
                else:
                    raise Exception("Token invalide")
            
            # Sinon vérifier comme JWT
            try:
                payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
                return {
                    'user_id': str(payload.get('user_id', '0')),
                    'username': payload.get('username', ''),
                    'role': payload.get('role', 'user')
                }
            except:
                raise Exception("Token invalide")
                
        except Exception as e:
            raise Exception(f"Erreur token: {str(e)}")
    
    @staticmethod
    def generate_token(user_id, username, role="user"):
        """Générer un nouveau token"""
        # Générer un token simple zenv_
        simple_token = f"zenv_{secrets.token_hex(32)}"
        
        # Sauvegarder dans GitHub
        tokens_db = GitHubManager.read_from_github('tokens/tokens.json', {'tokens': []})
        
        token_info = {
            'token': simple_token,
            'user_id': str(user_id),
            'username': username,
            'role': role,
            'created_at': datetime.now().isoformat(),
            'active': True
        }
        
        tokens_db['tokens'].append(token_info)
        GitHubManager.save_to_github('tokens/tokens.json', tokens_db, f'Generate token for {username}')
        
        return {
            'access_token': simple_token,
            'token_type': 'zenv',
            'expires_in': None,  # Jamais
            'user': {
                'id': str(user_id),
                'username': username,
                'role': role
            }
        }

class BadgeGenerator:
    """Générateur de badges"""
    
    @staticmethod
    def create_svg_badge(label: str, value: str, color: str = "blue") -> str:
        colors = {
            'blue': '#007ec6',
            'green': '#4c1',
            'red': '#e05d44',
            'orange': '#fe7d37',
            'yellow': '#dfb317'
        }
        
        color_hex = colors.get(color, colors['blue'])
        label_width = max(len(label) * 6 + 10, 30)
        value_width = max(len(value) * 6 + 10, 30)
        total_width = label_width + value_width
        
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
<linearGradient id="b" x2="0" y2="100%">
<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
<stop offset="1" stop-opacity=".1"/>
</linearGradient>
<mask id="a">
<rect width="{total_width}" height="20" rx="3" fill="#fff"/>
</mask>
<g mask="url(#a)">
<rect width="{label_width}" height="20" fill="{color_hex}"/>
<rect x="{label_width}" width="{value_width}" height="20" fill="#555"/>
<rect width="{total_width}" height="20" fill="url(#b)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
<text x="{label_width/2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
<text x="{label_width/2}" y="14">{label}</text>
<text x="{label_width + value_width/2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
<text x="{label_width + value_width/2}" y="14">{value}</text>
</g>
</svg>'''
        
        return svg

# ============================================================================
# DÉCORATEURS
# ============================================================================

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # Extraire le token
        auth_header = request.headers.get('Authorization')
        if auth_header:
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
            elif auth_header.startswith('Token '):
                token = auth_header.split(' ')[1]
            else:
                token = auth_header
        
        # Vérifier aussi dans les query params
        if not token:
            token = request.args.get('token')
        
        if not token:
            return jsonify({'error': 'Token manquant'}), 401
        
        try:
            # Vérifier le token
            user_data = SecurityUtils.verify_token(token)
            g.user_id = user_data['user_id']
            g.username = user_data['username']
            g.role = user_data['role']
        except Exception as e:
            return jsonify({'error': str(e)}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# ROUTES API
# ============================================================================

@app.route('/')
def index():
    return jsonify({
        'message': 'Zenv Package Hub API',
        'version': '3.0.0',
        'github_repo': f'{GITHUB_REPO}:{GITHUB_BRANCH}',
        'endpoints': {
            'auth': ['POST /api/auth/login', 'POST /api/auth/register', 'GET /api/auth/profile'],
            'packages': ['GET /api/packages', 'POST /api/packages/upload', 'GET /api/packages/download/<name>/<version>'],
            'badges': ['GET /api/badges', 'POST /api/badges', 'GET /badge/svg/<name>'],
            'tokens': ['POST /api/tokens/generate']
        },
        'token_formats': ['Bearer <token>', 'Token <token>', 'zenv_xxxxxxxx']
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'github': 'connected' if GitHubManager.init_github_repo() else 'disconnected'
    })

# ============================================================================
# AUTHENTIFICATION
# ============================================================================

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Username and password required'}), 400
    
    username = data['username']
    password = data['password']
    
    try:
        # Lire la base de données
        db = GitHubManager.read_from_github('database/zenv_hub.json')
        if not db or 'users' not in db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Chercher l'utilisateur
        user = None
        for u in db['users']:
            if u['username'] == username or u['email'] == username:
                user = u
                break
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Vérifier le mot de passe
        if not SecurityUtils.verify_password(password, user['password']):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Mettre à jour last_login
        user['last_login'] = datetime.now().isoformat()
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Login {username}')
        
        # Générer un token
        token_data = SecurityUtils.generate_token(user['id'], user['username'], user.get('role', 'user'))
        
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'role': user.get('role', 'user')
            },
            'token': token_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or 'username' not in data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Username, email and password required'}), 400
    
    username = data['username']
    email = data['email']
    password = data['password']
    
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    
    try:
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'users': [], 'packages': [], 'badges': []})
        
        # Vérifier si existe
        for user in db.get('users', []):
            if user['username'] == username:
                return jsonify({'error': 'Username already exists'}), 400
            if user['email'] == email:
                return jsonify({'error': 'Email already exists'}), 400
        
        # Créer nouvel utilisateur
        new_user = {
            'id': str(len(db['users']) + 1),
            'username': username,
            'email': email,
            'password': SecurityUtils.hash_password(password),
            'role': 'user',
            'created_at': datetime.now().isoformat(),
            'last_login': datetime.now().isoformat(),
            'is_verified': True
        }
        
        db['users'].append(new_user)
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Register {username}')
        
        # Générer token
        token_data = SecurityUtils.generate_token(new_user['id'], username, 'user')
        
        return jsonify({
            'message': 'Registration successful',
            'user': {
                'id': new_user['id'],
                'username': username,
                'email': email,
                'role': 'user'
            },
            'token': token_data
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/profile', methods=['GET'])
@token_required
def get_profile():
    try:
        db = GitHubManager.read_from_github('database/zenv_hub.json')
        
        if db and 'users' in db:
            for user in db['users']:
                if user['id'] == g.user_id:
                    return jsonify({
                        'user': {
                            'id': user['id'],
                            'username': user['username'],
                            'email': user['email'],
                            'role': user.get('role', 'user'),
                            'created_at': user.get('created_at'),
                            'last_login': user.get('last_login')
                        }
                    })
        
        return jsonify({'error': 'User not found'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# PACKAGES
# ============================================================================

@app.route('/api/packages', methods=['GET'])
def list_packages():
    """Lister tous les packages"""
    try:
        packages = GitHubManager.list_packages()
        
        # Lire les métadonnées depuis la DB
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        package_metadata = {p['name']: p for p in db.get('packages', [])}
        
        # Combiner les données
        result = []
        for pkg in packages:
            metadata = package_metadata.get(pkg['name'], {})
            result.append({
                'name': pkg['name'],
                'version': pkg['version'],
                'description': metadata.get('description', f'Package {pkg["name"]}'),
                'author': metadata.get('author', 'Unknown'),
                'downloads_count': metadata.get('downloads_count', 0),
                'filename': pkg['filename'],
                'size': pkg['size'],
                'download_url': pkg['download_url'],
                'updated_at': pkg['updated_at']
            })
        
        return jsonify({
            'packages': result,
            'count': len(result)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/upload', methods=['POST'])
@token_required
def upload_package():
    """Uploader un nouveau package"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        package_name = request.form.get('name')
        version = request.form.get('version')
        description = request.form.get('description', '')
        
        if not package_name or not version:
            return jsonify({'error': 'Package name and version required'}), 400
        
        # Upload sur GitHub
        success, download_url, file_size = GitHubManager.upload_package(file, package_name, version)
        
        if not success:
            return jsonify({'error': 'Failed to upload to GitHub'}), 500
        
        # Mettre à jour la base de données
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        
        # Vérifier si le package existe déjà
        package_exists = False
        for pkg in db['packages']:
            if pkg['name'] == package_name:
                pkg['version'] = version
                pkg['description'] = description
                pkg['updated_at'] = datetime.now().isoformat()
                pkg['downloads_count'] = pkg.get('downloads_count', 0)
                package_exists = True
                break
        
        if not package_exists:
            db['packages'].append({
                'name': package_name,
                'version': version,
                'description': description,
                'author': g.username,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'downloads_count': 0
            })
        
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Add/update package {package_name}')
        
        return jsonify({
            'message': 'Package uploaded successfully',
            'package': {
                'name': package_name,
                'version': version,
                'description': description,
                'filename': f"{package_name}-{version}.zv",
                'size': file_size,
                'download_url': download_url
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/packages/download/<package_name>/<version>', methods=['GET'])
def download_package(package_name, version):
    """Télécharger un package"""
    try:
        filename = f"{package_name}-{version}.zv"
        content = GitHubManager.download_package(package_name, filename)
        
        if content is None:
            return jsonify({'error': 'Package not found'}), 404
        
        # Mettre à jour les stats de téléchargement
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'packages': []})
        
        for pkg in db['packages']:
            if pkg['name'] == package_name:
                pkg['downloads_count'] = pkg.get('downloads_count', 0) + 1
                break
        
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Download {package_name}')
        
        # Créer une réponse avec le fichier
        response = Response(content, mimetype='application/octet-stream')
        response.headers.set('Content-Disposition', 'attachment', filename=filename)
        response.headers.set('Content-Length', len(content))
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# BADGES
# ============================================================================

@app.route('/api/badges', methods=['GET'])
def list_badges():
    """Lister tous les badges"""
    try:
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'badges': []})
        badges = db.get('badges', [])
        
        return jsonify({
            'badges': badges,
            'count': len(badges)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/badges', methods=['POST'])
@token_required
def create_badge():
    """Créer un nouveau badge"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'label' not in data or 'value' not in data:
        return jsonify({'error': 'Name, label and value required'}), 400
    
    name = data['name']
    label = data['label']
    value = data['value']
    color = data.get('color', 'blue')
    
    try:
        # Générer le badge SVG
        svg_content = BadgeGenerator.create_svg_badge(label, value, color)
        
        # Sauvegarder sur GitHub
        badge_path = f"badges/{name}.svg"
        GitHubManager.save_to_github(badge_path, svg_content, f'Create badge {name}')
        
        # Mettre à jour la base de données
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'badges': []})
        
        # Vérifier si existe
        badge_exists = False
        for badge in db['badges']:
            if badge['name'] == name:
                badge.update({
                    'label': label,
                    'value': value,
                    'color': color,
                    'updated_at': datetime.now().isoformat()
                })
                badge_exists = True
                break
        
        if not badge_exists:
            db['badges'].append({
                'name': name,
                'label': label,
                'value': value,
                'color': color,
                'created_by': g.username,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'usage_count': 0
            })
        
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Add/update badge {name}')
        
        badge_url = f"/badge/svg/{name}"
        
        return jsonify({
            'message': 'Badge created successfully',
            'badge': {
                'name': name,
                'label': label,
                'value': value,
                'color': color,
                'svg_url': badge_url,
                'markdown': f'![{label}: {value}]({badge_url})'
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/badge/svg/<name>', methods=['GET'])
def get_badge_svg(name):
    """Obtenir un badge SVG"""
    try:
        badge_path = f"badges/{name}.svg"
        svg_content = GitHubManager.read_from_github(badge_path)
        
        if svg_content is None:
            # Créer un badge 404
            svg_content = BadgeGenerator.create_svg_badge("404", "Not Found", "red")
        
        # Mettre à jour le compteur d'usage
        db = GitHubManager.read_from_github('database/zenv_hub.json', {'badges': []})
        
        for badge in db['badges']:
            if badge['name'] == name:
                badge['usage_count'] = badge.get('usage_count', 0) + 1
                break
        
        GitHubManager.save_to_github('database/zenv_hub.json', db, f'Use badge {name}')
        
        return Response(svg_content, mimetype='image/svg+xml')
        
    except Exception as e:
        svg_content = BadgeGenerator.create_svg_badge("Error", str(e)[:20], "red")
        return Response(svg_content, mimetype='image/svg+xml')

# ============================================================================
# TOKENS
# ============================================================================

@app.route('/api/tokens/generate', methods=['POST'])
@token_required
def generate_token():
    """Générer un nouveau token"""
    try:
        token_data = SecurityUtils.generate_token(g.user_id, g.username, g.role)
        
        return jsonify({
            'message': 'Token generated successfully',
            'token': token_data['access_token'],
            'user': token_data['user'],
            'note': 'This token never expires. Use it with Authorization: Bearer <token> or Authorization: Token <token>'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tokens/verify', methods=['GET'])
def verify_token():
    """Vérifier un token (pour le CLI)"""
    token = request.args.get('token')
    
    if not token:
        return jsonify({'error': 'Token required'}), 400
    
    try:
        user_data = SecurityUtils.verify_token(token)
        
        return jsonify({
            'valid': True,
            'user': user_data,
            'token_preview': token[:20] + '...' + token[-20:] if len(token) > 40 else token
        })
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'error': str(e)
        }), 401

# ============================================================================
# CLI ENDPOINTS
# ============================================================================

@app.route('/api/cli/publish', methods=['POST'])
def cli_publish():
    """Endpoint pour le CLI Zenv pour publier des packages"""
    token = request.headers.get('Authorization') or request.args.get('token')
    
    if not token:
        return jsonify({'error': 'Token required'}), 401
    
    try:
        # Vérifier le token
        user_data = SecurityUtils.verify_token(token)
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        package_name = request.form.get('name', file.filename.split('.')[0])
        version = request.form.get('version', '1.0.0')
        
        # Upload le package
        success, download_url, file_size = GitHubManager.upload_package(file, package_name, version)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Package {package_name} v{version} published successfully',
                'download_url': download_url,
                'size': file_size
            })
        else:
            return jsonify({'error': 'Failed to publish package'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cli/install/<package_name>', methods=['GET'])
def cli_install(package_name):
    """Endpoint pour le CLI Zenv pour installer des packages"""
    try:
        # Chercher le package
        packages = GitHubManager.list_packages()
        
        for pkg in packages:
            if pkg['name'] == package_name:
                # Télécharger le fichier
                content = GitHubManager.download_package(package_name, pkg['filename'])
                
                if content:
                    response = Response(content, mimetype='application/octet-stream')
                    response.headers.set('Content-Disposition', 'attachment', filename=pkg['filename'])
                    return response
        
        return jsonify({'error': f'Package {package_name} not found'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# INITIALISATION
# ============================================================================

def initialize_app():
    """Initialiser l'application"""
    print("=" * 60)
    print("🚀 Zenv Package Hub - GitHub Direct Storage")
    print("=" * 60)
    print(f"📦 GitHub Repo: {GITHUB_REPO}")
    print(f"🌿 Branch: {GITHUB_BRANCH}")
    print(f"👤 Username: {GITHUB_USERNAME}")
    print(f"🔑 Token: {GITHUB_TOKEN[:20]}...")
    print("-" * 60)
    
    # Initialiser GitHub
    if GitHubManager.init_github_repo():
        print("✅ GitHub initialized successfully")
    else:
        print("⚠️ GitHub initialization issues - some features may not work")
    
    print("=" * 60)
    print("📡 Server ready! Endpoints:")
    print("  • GET  /                    - API Documentation")
    print("  • POST /api/auth/login      - Login")
    print("  • POST /api/auth/register   - Register")
    print("  • GET  /api/packages        - List packages")
    print("  • POST /api/packages/upload - Upload package (token required)")
    print("  • POST /api/badges          - Create badge (token required)")
    print("  • POST /api/tokens/generate - Generate token (token required)")
    print("=" * 60)

# ============================================================================
# DÉMARRAGE
# ============================================================================

# Initialiser au démarrage
initialize_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True') == 'True'
    
    print(f"\n🌐 Starting server on http://0.0.0.0:{port}")
    print(f"🔧 Debug mode: {debug}")
    print(f"📊 Test with your token: zenv_ead27bf9d1b91e30729eb574a82e7287d4c9f35df9f8feb4f581452444350a5b")
    print("\n" + "=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
