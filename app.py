from flask import Flask, Response, request, jsonify, render_template
import requests
from db import get_db
from utils.svg import generate_badge_svg
from utils.base64 import image_to_base64
from db import init_db

init_db()  # 🔥 auto-création DB + badge officiel

app = Flask(__name__)

OFFICIAL_LOGO_URL = "https://raw.githubusercontent.com/gopu-inc/gsql/refs/heads/main/GSQL"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/badge")
def official_badge():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT label, message, color FROM badges WHERE official = TRUE LIMIT 1")
    label, message, color = cur.fetchone()

    logo = requests.get(OFFICIAL_LOGO_URL).text

    svg = generate_badge_svg(label, message, color, logo)

    cur.close()
    conn.close()

    return Response(svg, mimetype="image/svg+xml")

@app.route("/badge/<slug>")
def user_badge(slug):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT label, message, color, logo_base64
        FROM badges WHERE slug = %s
    """, (slug,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return "Badge not found", 404

    label, message, color, logo_base64 = row
    svg = generate_badge_svg(label, message, color, logo_base64)

    return Response(svg, mimetype="image/svg+xml")

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    slug = file.filename.split(".")[0]

    base64_img = image_to_base64(file)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO badges (slug, label, message, color, logo_base64)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (slug) DO NOTHING
    """, (
        slug,
        "Custom",
        slug,
        "#22c55e",
        base64_img
    ))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "badge_url": f"/badge/{slug}"
    })

if __name__ == "__main__":
    app.run()
