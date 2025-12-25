from flask import Flask, Response, request, jsonify, render_template
import requests
from db import get_db
from utils.svg import generate_badge_svg
from utils.base64 import image_to_base64
import threading
from db import init_db
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialisation de la base de données
threading.Thread(target=init_db, daemon=True).start()

app = Flask(__name__)

OFFICIAL_LOGO_URL = "https://raw.githubusercontent.com/gopu-inc/gsql/refs/heads/main/GSQL"

@app.route("/")
def index():
    """Page d'accueil avec documentation"""
    return render_template("index.html")

@app.route("/health")
def health():
    """Endpoint de santé"""
    return "GSQL V3.1.2 badge manager by gopu.inc", 200

@app.route("/badge")
def official_badge():
    """Badge officiel - utilisé comme exemple"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT label, message, color FROM badges WHERE official = TRUE LIMIT 1")
        row = cur.fetchone()
        
        if not row:
            # Valeurs par défaut si pas de badge officiel
            label, message, color = "GSQL", "3.1.2", "#007ec6"
        else:
            label, message, color = row

        # Récupération du logo officiel
        try:
            logo_response = requests.get(OFFICIAL_LOGO_URL, timeout=5)
            logo = logo_response.text if logo_response.status_code == 200 else None
        except:
            logo = None

        svg = generate_badge_svg(label, message, color, logo)

        cur.close()
        conn.close()
        
        response = Response(svg, mimetype="image/svg+xml")
        response.headers['Cache-Control'] = 'public, max-age=300'  # Cache 5 minutes
        return response
        
    except Exception as e:
        logger.error(f"Error generating official badge: {e}")
        return Response(generate_badge_svg("Error", "500", "#e05d44"), 
                       mimetype="image/svg+xml"), 500

@app.route("/badge/<slug>")
def user_badge(slug):
    """Badge personnalisé par slug"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT label, message, color, logo_base64
            FROM badges WHERE slug = %s
        """, (slug,))

        row = cur.fetchone()
        
        if not row:
            # Badge 404 stylé
            svg = generate_badge_svg("404", "Not Found", "#9f9f9f")
            response = Response(svg, mimetype="image/svg+xml")
            response.headers['Cache-Control'] = 'public, max-age=60'
            return response, 404

        label, message, color, logo_base64 = row
        svg = generate_badge_svg(label, message, color, logo_base64)

        cur.close()
        conn.close()
        
        response = Response(svg, mimetype="image/svg+xml")
        response.headers['Cache-Control'] = 'public, max-age=3600'  # Cache 1 heure
        return response
        
    except Exception as e:
        logger.error(f"Error generating badge for slug {slug}: {e}")
        return Response(generate_badge_svg("Error", "500", "#e05d44"), 
                       mimetype="image/svg+xml"), 500

@app.route("/create", methods=["POST"])
def create_badge():
    """API pour créer/modifier un badge"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        slug = data.get('slug')
        label = data.get('label', 'Custom')
        message = data.get('message', '')
        color = data.get('color', '#22c55e')
        logo_url = data.get('logo_url')
        logo_base64 = data.get('logo_base64')
        
        if not slug:
            return jsonify({"error": "Slug is required"}), 400
            
        # Télécharger le logo depuis une URL si fourni
        if logo_url and not logo_base64:
            try:
                response = requests.get(logo_url, timeout=10)
                if response.status_code == 200:
                    import base64
                    logo_base64 = base64.b64encode(response.content).decode('utf-8')
            except Exception as e:
                logger.warning(f"Could not download logo from {logo_url}: {e}")
                logo_base64 = None
        
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO badges (slug, label, message, color, logo_base64, official)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                message = EXCLUDED.message,
                color = EXCLUDED.color,
                logo_base64 = EXCLUDED.logo_base64
        """, (slug, label, message, color, logo_base64))

        conn.commit()
        badge_url = f"{request.host_url.rstrip('/')}/badge/{slug}"
        
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "slug": slug,
            "badge_url": badge_url,
            "markdown": f"![{label}]({badge_url})",
            "html": f'<img src="{badge_url}" alt="{label}: {message}">'
        })
        
    except Exception as e:
        logger.error(f"Error creating badge: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload():
    """Upload de badge via formulaire (rétrocompatible)"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
            
        file = request.files["file"]
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
            
        slug = file.filename.split(".")[0]
        base64_img = image_to_base64(file)
        
        # Options personnalisables via paramètres
        label = request.form.get('label', 'Custom')
        message = request.form.get('message', slug)
        color = request.form.get('color', '#22c55e')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO badges (slug, label, message, color, logo_base64, official)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                message = EXCLUDED.message,
                color = EXCLUDED.color,
                logo_base64 = EXCLUDED.logo_base64
        """, (slug, label, message, color, base64_img))

        conn.commit()
        badge_url = f"{request.host_url.rstrip('/')}/badge/{slug}"
        
        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "slug": slug,
            "badge_url": badge_url,
            "markdown": f"![{label}]({badge_url})"
        })
        
    except Exception as e:
        logger.error(f"Error uploading badge: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/list")
def list_badges():
    """Liste tous les badges disponibles"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT slug, label, message, color, created_at
            FROM badges WHERE official = FALSE
            ORDER BY created_at DESC
        """)
        
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
        
        cur.close()
        conn.close()
        
        return jsonify({
            "count": len(badges),
            "badges": badges
        })
        
    except Exception as e:
        logger.error(f"Error listing badges: {e}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    """Gestion des erreurs 404"""
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(error):
    """Gestion des erreurs 500"""
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
