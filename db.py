import psycopg2
from config import DATABASE_URL

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # 1️⃣ Créer la table badges
    cur.execute("""
    CREATE TABLE IF NOT EXISTS badges (
        id SERIAL PRIMARY KEY,
        slug TEXT UNIQUE NOT NULL,
        label TEXT NOT NULL,
        message TEXT NOT NULL,
        color TEXT NOT NULL,
        logo_base64 TEXT,
        official BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2️⃣ Insérer le badge officiel s’il n’existe pas
    cur.execute("""
    INSERT INTO badges (slug, label, message, color, official)
    VALUES (%s, %s, %s, %s, TRUE)
    ON CONFLICT (slug) DO NOTHING;
    """, (
        "official",
        "GSQL",
        "powered by Gopu",
        "#0A84FF"
    ))

    conn.commit()
    cur.close()
    conn.close()
