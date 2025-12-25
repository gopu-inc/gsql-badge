from flask import Flask, Response, request, jsonify, render_template
import requests
from db import get_db
from utils.svg import generate_badge_svg
from utils.base64 import image_to_base64, validate_image_file
from utils.security import clean_slug, sanitize_text, validate_color, rate_limit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
from db import init_db
import logging
import os
from werkzeug.middleware.proxy_fix import ProxyFix

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialisation de la base de données
threading.Thread(target=init_db, daemon=True).start()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)  # Pour le bon fonctionnement derrière proxy

# Rate limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

OFFICIAL_LOGO_URL = "https://raw.githubusercontent.com/gopu-inc/gsql/refs/heads/main/GSQL"
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico'}
MAX_BADGES_PER_USER = 100

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    """Page d'accueil avec documentation"""
    return render_template("index.html")

@app.route("/health")
def health():
    """Endpoint de santé"""
    return jsonify({
        "status": "healthy",
        "service": "GSQL Badge Manager",
        "version": "3.1.2",
        "author": "gopu.inc"
    }), 200

@app.route("/badge")
@limiter.limit("100/hour")
def official_badge():
    """Badge officiel - utilisé comme exemple"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT label, message, color FROM badges WHERE official = TRUE LIMIT 1")
        row = cur.fetchone()
        
        if not row:
            label, message, color = "GSQL", "3.1.2", "#007ec6"
        else:
            label, message, color = row
            label = sanitize_text(label, max_length=50)
            message = sanitize_text(message, max_length=100)

        # Récupération du logo officiel avec timeout
        try:
            logo_response = requests.get(OFFICIAL_LOGO_URL, timeout=3)
            if logo_response.status_code == 200:
                logo = logo_response.text
            else:
                logo = None
        except requests.RequestException:
            logo = None

        svg = generate_badge_svg(label, message, color, logo)
        cur.close()
        conn.close()
        
        response = Response(svg, mimetype="image/svg+xml")
        response.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=60'
        response.headers['Content-Security-Policy'] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
        return response
        
    except Exception as e:
        logger.error(f"Error generating official badge: {e}")
        error_svg = generate_badge_svg("Error", "500", "#e05d44")
        return Response(error_svg, mimetype="image/svg+xml"), 500

@app.route("/badge/<slug>")
@limiter.limit("500/hour")
def user_badge(slug):
    """Badge personnalisé par slug"""
    try:
        # Validation du slug
        if not slug or len(slug) > 100:
            return badge_error("Invalid slug", "#9f9f9f", 400)
        
        # Nettoyage du slug
        clean_slug_value = clean_slug(slug)
        if clean_slug_value != slug:
            logger.warning(f"Slug cleaned: {slug} -> {clean_slug_value}")
        
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT label, message, color, logo_base64
            FROM badges WHERE slug = %s
        """, (clean_slug_value,))

        row = cur.fetchone()
        
        if not row:
            svg = generate_badge_svg("404", "Not Found", "#9f9f9f")
            response = Response(svg, mimetype="image/svg+xml")
            response.headers['Cache-Control'] = 'public, max-age=300'
            return response, 404

        label, message, color, logo_base64 = row
        # Sanitisation des données
        label = sanitize_text(label, max_length=50)
        message = sanitize_text(message, max_length=100)
        color = validate_color(color)
        
        svg = generate_badge_svg(label, message, color, logo_base64)
        cur.close()
        conn.close()
        
        response = Response(svg, mimetype="image/svg+xml")
        response.headers['Cache-Control'] = 'public, max-age=3600, stale-while-revalidate=300'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
        
    except Exception as e:
        logger.error(f"Error generating badge for slug {slug}: {e}")
        return badge_error("Server Error", "#e05d44", 500)

def badge_error(message, color, status_code):
    """Helper pour générer des badges d'erreur"""
    svg = generate_badge_svg("Error", message, color)
    response = Response(svg, mimetype="image/svg+xml")
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response, status_code

@app.route("/create", methods=["POST"])
@limiter.limit("50/hour")
def create_badge():
    """API pour créer/modifier un badge"""
    try:
        data = request.get_json(silent=True) or {}
        
        # Validation des données requises
        slug = data.get('slug')
        if not slug or not isinstance(slug, str):
            return jsonify({"error": "Valid slug is required"}), 400
        
        # Nettoyage et validation du slug
        clean_slug_value = clean_slug(slug)
        if len(clean_slug_value) > 100:
            return jsonify({"error": "Slug too long (max 100 chars)"}), 400
        
        label = sanitize_text(data.get('label', 'Custom'), max_length=50)
        message = sanitize_text(data.get('message', clean_slug_value), max_length=100)
        color = validate_color(data.get('color', '#22c55e'))
        
        # Vérification du nombre de badges existants
        client_ip = request.remote_addr
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM badges WHERE created_by_ip = %s", (client_ip,))
        count = cur.fetchone()[0]
        
        if count >= MAX_BADGES_PER_USER:
            cur.close()
            conn.close()
            return jsonify({"error": f"Maximum badges limit reached ({MAX_BADGES_PER_USER})"}), 429
        
        # Gestion du logo
        logo_base64 = data.get('logo_base64')
        logo_url = data.get('logo_url')
        
        if logo_url and not logo_base64:
            try:
                # Validation de l'URL
                if not logo_url.startswith(('http://', 'https://')):
                    raise ValueError("Invalid URL scheme")
                
                response = requests.get(logo_url, timeout=5, stream=True)
                response.raise_for_status()
                
                # Vérification de la taille
                content_length = response.headers.get('Content-Length')
                if content_length and int(content_length) > MAX_FILE_SIZE:
                    raise ValueError("Logo too large")
                
                import base64
                from io import BytesIO
                
                # Lecture par morceaux pour éviter les gros fichiers
                content = BytesIO()
                for chunk in response.iter_content(chunk_size=8192):
                    if len(content.getvalue()) > MAX_FILE_SIZE:
                        raise ValueError("Logo too large")
                    content.write(chunk)
                
                logo_base64 = base64.b64encode(content.getvalue()).decode('utf-8')
                
            except Exception as e:
                logger.warning(f"Could not download logo from {logo_url}: {e}")
                logo_base64 = None
        
        # Insertion dans la base de données
        cur.execute("""
            INSERT INTO badges (slug, label, message, color, logo_base64, created_by_ip, official)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                message = EXCLUDED.message,
                color = EXCLUDED.color,
                logo_base64 = EXCLUDED.logo_base64,
                updated_at = CURRENT_TIMESTAMP,
                created_by_ip = EXCLUDED.created_by_ip
            RETURNING created_at
        """, (clean_slug_value, label, message, color, logo_base64, client_ip))

        conn.commit()
        created_at = cur.fetchone()[0]
        
        badge_url = f"{request.host_url.rstrip('/')}/badge/{clean_slug_value}"
        markdown = f"![{label}: {message}]({badge_url})"
        html = f'<img src="{badge_url}" alt="{label}: {message}" title="{label}: {message}">'
        
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "slug": clean_slug_value,
            "label": label,
            "message": message,
            "color": color,
            "badge_url": badge_url,
            "markdown": markdown,
            "html": html,
            "created_at": created_at.isoformat() if created_at else None,
            "direct_url": badge_url
        })
        
    except Exception as e:
        logger.error(f"Error creating badge: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
@limiter.limit("20/hour")
def upload():
    """Upload de badge via formulaire"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
            
        file = request.files["file"]
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Validation du fichier
        if not allowed_file(file.filename):
            return jsonify({"error": f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
        
        # Vérification de la taille
        file.seek(0, 2)  # Aller à la fin
        file_size = file.tell()
        file.seek(0)  # Retourner au début
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({"error": f"File too large (max {MAX_FILE_SIZE//1024//1024}MB)"}), 400
        
        # Validation du contenu de l'image
        if not validate_image_file(file):
            return jsonify({"error": "Invalid image file"}), 400
        
        # Récupération des paramètres
        slug = clean_slug(request.form.get('slug') or file.filename.split(".")[0])
        label = sanitize_text(request.form.get('label', 'Custom'), max_length=50)
        message = sanitize_text(request.form.get('message', slug), max_length=100)
        color = validate_color(request.form.get('color', '#22c55e'))
        
        if not slug:
            return jsonify({"error": "Could not generate valid slug from filename"}), 400
        
        # Conversion en base64
        base64_img = image_to_base64(file)
        if not base64_img:
            return jsonify({"error": "Could not process image"}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO badges (slug, label, message, color, logo_base64, created_by_ip, official)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                message = EXCLUDED.message,
                color = EXCLUDED.color,
                logo_base64 = EXCLUDED.logo_base64,
                updated_at = CURRENT_TIMESTAMP
        """, (slug, label, message, color, base64_img, request.remote_addr))

        conn.commit()
        badge_url = f"{request.host_url.rstrip('/')}/badge/{slug}"
        
        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "slug": slug,
            "label": label,
            "message": message,
            "color": color,
            "badge_url": badge_url,
            "markdown": f"![{label}]({badge_url})",
            "html": f'<img src="{badge_url}" alt="{label}: {message}">',
            "direct_url": badge_url
        })
        
    except Exception as e:
        logger.error(f"Error uploading badge: {e}")
        return jsonify({"error": "Upload failed"}), 500

@app.route("/list")
@limiter.limit("30/minute")
def list_badges():
    """Liste tous les badges disponibles"""
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, int(request.args.get('per_page', 20)))
        offset = (page - 1) * per_page
        
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT slug, label, message, color, created_at
            FROM badges WHERE official = FALSE
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        
        badges = []
        for row in cur.fetchall():
            slug, label, message, color, created_at = row
            badges.append({
                "slug": slug,
                "label": label,
                "message": message,
                "color": color,
                "badge_url": f"{request.host_url.rstrip('/')}/badge/{slug}",
                "created_at": created_at.isoformat() if created_at else None
            })
        
        # Comptage total
        cur.execute("SELECT COUNT(*) FROM badges WHERE official = FALSE")
        total = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
            "badges": badges
        })
        
    except Exception as e:
        logger.error(f"Error listing badges: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/badge/<slug>/delete", methods=["POST"])
@limiter.limit("10/hour")
def delete_badge(slug):
    """Supprimer un badge (admin)"""
    try:
        # Vérification de l'authentification (basique pour l'exemple)
        auth_token = request.headers.get('X-Admin-Token')
        if not auth_token or auth_token != os.environ.get('ADMIN_TOKEN', ''):
            return jsonify({"error": "Unauthorized"}), 401
        
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("DELETE FROM badges WHERE slug = %s RETURNING slug", (slug,))
        deleted = cur.fetchone()
        
        if not deleted:
            cur.close()
            conn.close()
            return jsonify({"error": "Badge not found"}), 404
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Badge {slug} deleted"
        })
        
    except Exception as e:
        logger.error(f"Error deleting badge {slug}: {e}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    """Gestion des erreurs 404"""
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    """Gestion du rate limiting"""
    return jsonify({"error": "Rate limit exceeded", "message": str(e.description)}), 429

@app.errorhandler(500)
def server_error(error):
    """Gestion des erreurs 500"""
    logger.error(f"Server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("DEBUG", "False").lower() == "true")
