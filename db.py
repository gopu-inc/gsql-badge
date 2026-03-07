import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL
import logging
import time
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

# Connection pool pour améliorer les performances
connection_pool = None

def init_connection_pool():
    """Initialise le pool de connexions PostgreSQL"""
    global connection_pool
    try:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1,  # min connections
            20,  # max connections
            DATABASE_URL,
            cursor_factory=RealDictCursor
        )
        logger.info("Connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize connection pool: {e}")
        raise

def get_db():
    """Récupère une connexion depuis le pool"""
    global connection_pool
    if connection_pool is None:
        init_connection_pool()
    
    try:
        conn = connection_pool.getconn()
        return conn
    except Exception as e:
        logger.error(f"Failed to get connection from pool: {e}")
        # Fallback: création d'une connexion directe
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def return_db(conn):
    """Retourne une connexion au pool"""
    global connection_pool
    if connection_pool and conn:
        try:
            connection_pool.putconn(conn)
        except:
            conn.close()

def init_db():
    """Initialise la base de données avec toutes les tables nécessaires"""
    conn = None
    cur = None
    
    try:
        conn = get_db()
        cur = conn.cursor()

        # Table des badges
        cur.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            message TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#22c55e',
            logo_base64 TEXT,
            official BOOLEAN DEFAULT FALSE,
            views INTEGER DEFAULT 0,
            last_viewed TIMESTAMP,
            created_by_ip INET,
            user_agent TEXT,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- Indexes pour les performances
            CONSTRAINT valid_color CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
            CONSTRAINT valid_slug CHECK (slug ~ '^[a-z0-9-]+$' AND length(slug) <= 100)
        );
        """)

        # Index pour optimiser les recherches
        cur.execute("CREATE INDEX IF NOT EXISTS idx_badges_slug ON badges(slug);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_badges_official ON badges(official);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_badges_created_at ON badges(created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_badges_views ON badges(views DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_badges_created_by_ip ON badges(created_by_ip);")

        # Table des statistiques
        cur.execute("""
        CREATE TABLE IF NOT EXISTS statistics (
            id SERIAL PRIMARY KEY,
            date DATE UNIQUE NOT NULL,
            total_badges INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            new_badges INTEGER DEFAULT 0,
            unique_visitors INTEGER DEFAULT 0,
            api_calls INTEGER DEFAULT 0,
            top_badges JSONB DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Table des utilisateurs (pour éventuelle authentification)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            api_key TEXT UNIQUE,
            is_admin BOOLEAN DEFAULT FALSE,
            max_badges INTEGER DEFAULT 100,
            badges_created INTEGER DEFAULT 0,
            last_login TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            CONSTRAINT valid_username CHECK (username ~ '^[a-zA-Z0-9_-]{3,50}$')
        );
        """)

        # Table des logs d'activité
        cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            ip_address INET,
            user_agent TEXT,
            endpoint TEXT NOT NULL,
            method TEXT NOT NULL,
            status_code INTEGER,
            response_time_ms INTEGER,
            badge_slug TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_created_at ON activity_logs(created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_endpoint ON activity_logs(endpoint);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_ip ON activity_logs(ip_address);")

        # Table des taux limites (rate limiting)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            id SERIAL PRIMARY KEY,
            ip_address INET NOT NULL,
            endpoint TEXT NOT NULL,
            requests_count INTEGER DEFAULT 1,
            first_request TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_request TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(ip_address, endpoint)
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_ip_endpoint ON rate_limits(ip_address, endpoint);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_last_request ON rate_limits(last_request);")

        # Table des thèmes de badges prédéfinis
        cur.execute("""
        CREATE TABLE IF NOT EXISTS badge_themes (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            label_color TEXT NOT NULL DEFAULT '#555555',
            message_color TEXT NOT NULL DEFAULT '#007ec6',
            description TEXT,
            is_public BOOLEAN DEFAULT TRUE,
            usage_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Insérer des thèmes par défaut
        cur.execute("""
        INSERT INTO badge_themes (name, label_color, message_color, description)
        VALUES 
            ('default', '#555555', '#007ec6', 'Theme par défaut shields.io'),
            ('success', '#555555', '#4c1', 'Pour les succès/builds passants'),
            ('important', '#555555', '#e05d44', 'Pour les erreurs/alertes'),
            ('informational', '#555555', '#007ec6', 'Pour les informations'),
            ('warning', '#555555', '#dfb317', 'Pour les avertissements'),
            ('inactive', '#555555', '#9f9f9f', 'Pour les status inactifs'),
            ('blue', '#555555', '#0A84FF', 'Bleu GSQL'),
            ('purple', '#555555', '#8b5cf6', 'Violet moderne'),
            ('pink', '#555555', '#db2777', 'Rose vif'),
            ('orange', '#555555', '#ea580c', 'Orange chaleureux')
        ON CONFLICT (name) DO NOTHING;
        """)

        # Table des favoris
        cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id SERIAL PRIMARY KEY,
            badge_slug TEXT NOT NULL REFERENCES badges(slug) ON DELETE CASCADE,
            ip_address INET NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(badge_slug, ip_address)
        );
        """)

        # Table des rapports de problèmes
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            badge_slug TEXT NOT NULL REFERENCES badges(slug) ON DELETE CASCADE,
            report_type TEXT NOT NULL,
            description TEXT,
            reporter_ip INET,
            status TEXT DEFAULT 'pending',
            resolved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Table de cache pour les badges générés
        cur.execute("""
        CREATE TABLE IF NOT EXISTS badge_cache (
            id SERIAL PRIMARY KEY,
            badge_slug TEXT UNIQUE NOT NULL REFERENCES badges(slug) ON DELETE CASCADE,
            svg_content TEXT NOT NULL,
            hash TEXT NOT NULL,
            hits INTEGER DEFAULT 0,
            last_hit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON badge_cache(expires_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cache_hash ON badge_cache(hash);")

        # 2️⃣ Insérer le badge officiel s'il n'existe pas
        cur.execute("""
        INSERT INTO badges (slug, label, message, color, official, metadata)
        VALUES (%s, %s, %s, %s, TRUE, %s)
        ON CONFLICT (slug) DO UPDATE SET
            label = EXCLUDED.label,
            message = EXCLUDED.message,
            color = EXCLUDED.color,
            metadata = EXCLUDED.metadata,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
        """, (
            "official",
            "GSQL",
            "powered by Gopu",
            "#0A84FF",
            json.dumps({
                "description": "Badge officiel GSQL",
                "category": "branding",
                "tags": ["official", "gsql", "gopu"],
                "example_urls": [
                    "https://github.com/gopu-inc",
                    "https://render.com"
                ]
            })
        ))

        # 3️⃣ Créer les fonctions PostgreSQL

        # Fonction pour mettre à jour le timestamp updated_at
        cur.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        """)

        # Trigger pour badges
        cur.execute("""
        DROP TRIGGER IF EXISTS update_badges_updated_at ON badges;
        CREATE TRIGGER update_badges_updated_at
            BEFORE UPDATE ON badges
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)

        # Fonction pour incrémenter les vues
        cur.execute("""
        CREATE OR REPLACE FUNCTION increment_badge_views(badge_slug TEXT)
        RETURNS INTEGER AS $$
        DECLARE
            current_views INTEGER;
        BEGIN
            UPDATE badges 
            SET views = views + 1, 
                last_viewed = CURRENT_TIMESTAMP
            WHERE slug = badge_slug
            RETURNING views INTO current_views;
            
            RETURN current_views;
        END;
        $$ language 'plpgsql';
        """)

        # Fonction pour nettoyer le cache expiré
        cur.execute("""
        CREATE OR REPLACE FUNCTION cleanup_expired_cache()
        RETURNS INTEGER AS $$
        DECLARE
            deleted_count INTEGER;
        BEGIN
            DELETE FROM badge_cache 
            WHERE expires_at < CURRENT_TIMESTAMP
            RETURNING COUNT(*) INTO deleted_count;
            
            RETURN deleted_count;
        END;
        $$ language 'plpgsql';
        """)

        # Fonction pour mettre à jour les statistiques quotidiennes
        cur.execute("""
        CREATE OR REPLACE FUNCTION update_daily_statistics()
        RETURNS VOID AS $$
        BEGIN
            INSERT INTO statistics (date, total_badges, total_views, new_badges, unique_visitors, top_badges)
            SELECT 
                CURRENT_DATE,
                COUNT(*) as total_badges,
                COALESCE(SUM(views), 0) as total_views,
                COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END) as new_badges,
                COUNT(DISTINCT created_by_ip) as unique_visitors,
                COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'slug', slug,
                            'label', label,
                            'views', views
                        ) ORDER BY views DESC LIMIT 10
                    ),
                    '[]'::jsonb
                ) as top_badges
            FROM badges
            ON CONFLICT (date) DO UPDATE SET
                total_badges = EXCLUDED.total_badges,
                total_views = EXCLUDED.total_views,
                new_badges = EXCLUDED.new_badges,
                unique_visitors = EXCLUDED.unique_visitors,
                top_badges = EXCLUDED.top_badges,
                updated_at = CURRENT_TIMESTAMP;
        END;
        $$ language 'plpgsql';
        """)

        # Fonction pour vérifier le rate limiting
        cur.execute("""
        CREATE OR REPLACE FUNCTION check_rate_limit(
            p_ip_address INET,
            p_endpoint TEXT,
            p_limit_per_hour INTEGER
        )
        RETURNS BOOLEAN AS $$
        DECLARE
            request_count INTEGER;
            time_window TIMESTAMP;
        BEGIN
            -- Définir la fenêtre temporelle (1 heure)
            time_window := CURRENT_TIMESTAMP - INTERVAL '1 hour';
            
            -- Supprimer les entrées anciennes
            DELETE FROM rate_limits 
            WHERE last_request < time_window 
              AND ip_address = p_ip_address 
              AND endpoint = p_endpoint;
            
            -- Compter les requêtes récentes
            SELECT requests_count INTO request_count
            FROM rate_limits
            WHERE ip_address = p_ip_address 
              AND endpoint = p_endpoint;
            
            IF request_count IS NULL THEN
                -- Première requête
                INSERT INTO rate_limits (ip_address, endpoint, requests_count)
                VALUES (p_ip_address, p_endpoint, 1);
                RETURN TRUE;
            ELSIF request_count < p_limit_per_hour THEN
                -- Incrémenter le compteur
                UPDATE rate_limits 
                SET requests_count = requests_count + 1,
                    last_request = CURRENT_TIMESTAMP
                WHERE ip_address = p_ip_address 
                  AND endpoint = p_endpoint;
                RETURN TRUE;
            ELSE
                -- Limite atteinte
                UPDATE rate_limits 
                SET last_request = CURRENT_TIMESTAMP
                WHERE ip_address = p_ip_address 
                  AND endpoint = p_endpoint;
                RETURN FALSE;
            END IF;
        END;
        $$ language 'plpgsql';
        """)

        conn.commit()
        logger.info("Database initialized successfully with all tables and functions")
        
        # Lancer le nettoyage initial
        cur.execute("SELECT cleanup_expired_cache();")
        cleanup_result = cur.fetchone()
        logger.info(f"Initial cache cleanup removed {cleanup_result['cleanup_expired_cache']} expired entries")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def get_badge(slug):
    """Récupère un badge par son slug et incrémente le compteur de vues"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Récupérer le badge
        cur.execute("""
            SELECT b.*, 
                   COALESCE(
                       (SELECT COUNT(*) FROM favorites WHERE badge_slug = b.slug),
                       0
                   ) as favorite_count,
                   COALESCE(
                       (SELECT svg_content FROM badge_cache 
                        WHERE badge_slug = b.slug 
                          AND expires_at > CURRENT_TIMESTAMP
                        LIMIT 1),
                       NULL
                   ) as cached_svg
            FROM badges b
            WHERE b.slug = %s
        """, (slug,))
        
        badge = cur.fetchone()
        
        if badge:
            # Incrémenter les vues
            cur.execute("SELECT increment_badge_views(%s)", (slug,))
            conn.commit()
            
            # Mettre à jour les statistiques quotidiennes
            cur.execute("SELECT update_daily_statistics()")
            conn.commit()
        
        return badge
        
    except Exception as e:
        logger.error(f"Error getting badge {slug}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def create_badge(slug, label, message, color, logo_base64=None, ip_address=None, user_agent=None, metadata=None):
    """Crée ou met à jour un badge"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        if metadata is None:
            metadata = {}
        
        cur.execute("""
            INSERT INTO badges (slug, label, message, color, logo_base64, 
                               created_by_ip, user_agent, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                label = EXCLUDED.label,
                message = EXCLUDED.message,
                color = EXCLUDED.color,
                logo_base64 = EXCLUDED.logo_base64,
                user_agent = EXCLUDED.user_agent,
                metadata = badges.metadata || EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, slug, label, message, color, 
                     created_at, views, metadata;
        """, (slug, label, message, color, logo_base64, ip_address, user_agent, json.dumps(metadata)))
        
        result = cur.fetchone()
        conn.commit()
        
        # Nettoyer le cache pour ce badge
        cur.execute("DELETE FROM badge_cache WHERE badge_slug = %s", (slug,))
        conn.commit()
        
        # Mettre à jour les statistiques quotidiennes
        cur.execute("SELECT update_daily_statistics()")
        conn.commit()
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating badge {slug}: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def cache_badge_svg(slug, svg_content, ttl_hours=24):
    """Met en cache le SVG d'un badge"""
    import hashlib
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Générer un hash du contenu
        content_hash = hashlib.md5(svg_content.encode()).hexdigest()
        
        cur.execute("""
            INSERT INTO badge_cache (badge_slug, svg_content, hash, expires_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '%s hours')
            ON CONFLICT (badge_slug) DO UPDATE SET
                svg_content = EXCLUDED.svg_content,
                hash = EXCLUDED.hash,
                hits = badge_cache.hits + 1,
                last_hit = CURRENT_TIMESTAMP,
                expires_at = EXCLUDED.expires_at;
        """, (slug, svg_content, content_hash, ttl_hours))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error caching badge {slug}: {e}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def get_cached_badge(slug):
    """Récupère un badge depuis le cache"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE badge_cache 
            SET hits = hits + 1,
                last_hit = CURRENT_TIMESTAMP
            WHERE badge_slug = %s 
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING svg_content;
        """, (slug,))
        
        result = cur.fetchone()
        conn.commit()
        
        if result:
            return result['svg_content']
        return None
        
    except Exception as e:
        logger.error(f"Error getting cached badge {slug}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def log_activity(ip_address, user_agent, endpoint, method, status_code, 
                 response_time_ms, badge_slug=None, error_message=None):
    """Log une activité dans la base de données"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO activity_logs 
                (ip_address, user_agent, endpoint, method, status_code, 
                 response_time_ms, badge_slug, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (ip_address, user_agent, endpoint, method, status_code, 
              response_time_ms, badge_slug, error_message))
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"Error logging activity: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def check_rate_limit_db(ip_address, endpoint, limit_per_hour):
    """Vérifie le rate limiting via la base de données"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT check_rate_limit(%s, %s, %s) as allowed", 
                   (ip_address, endpoint, limit_per_hour))
        
        result = cur.fetchone()
        return result['allowed']
        
    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        return True  # En cas d'erreur, autoriser la requête
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def get_statistics(days=30):
    """Récupère les statistiques des N derniers jours"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT date, total_badges, total_views, new_badges, 
                   unique_visitors, api_calls, top_badges
            FROM statistics
            WHERE date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date DESC;
        """, (days,))
        
        daily_stats = cur.fetchall()
        
        # Statistiques globales
        cur.execute("""
            SELECT 
                COUNT(*) as total_badges,
                SUM(views) as total_views,
                COUNT(DISTINCT created_by_ip) as total_creators,
                AVG(views) as avg_views_per_badge,
                MAX(views) as max_views,
                COUNT(CASE WHEN created_at >= CURRENT_DATE - INTERVAL '7 days' THEN 1 END) as badges_last_7_days,
                COUNT(CASE WHEN created_at >= CURRENT_DATE - INTERVAL '24 hours' THEN 1 END) as badges_last_24_hours
            FROM badges
            WHERE official = FALSE;
        """)
        
        global_stats = cur.fetchone()
        
        # Badges les plus populaires
        cur.execute("""
            SELECT slug, label, message, color, views, created_at
            FROM badges
            WHERE official = FALSE
            ORDER BY views DESC
            LIMIT 10;
        """)
        
        top_badges = cur.fetchall()
        
        # Activité récente
        cur.execute("""
            SELECT endpoint, method, status_code, COUNT(*) as count
            FROM activity_logs
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            GROUP BY endpoint, method, status_code
            ORDER BY count DESC
            LIMIT 20;
        """)
        
        recent_activity = cur.fetchall()
        
        return {
            'daily_stats': daily_stats,
            'global_stats': global_stats,
            'top_badges': top_badges,
            'recent_activity': recent_activity,
            'generated_at': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def search_badges(query, page=1, per_page=20):
    """Recherche des badges"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        offset = (page - 1) * per_page
        
        # Recherche par slug, label ou message
        cur.execute("""
            SELECT slug, label, message, color, views, created_at,
                   ts_rank_cd(
                       setweight(to_tsvector('english', slug), 'A') ||
                       setweight(to_tsvector('english', label), 'B') ||
                       setweight(to_tsvector('english', message), 'C'),
                       plainto_tsquery('english', %s)
                   ) as rank
            FROM badges
            WHERE official = FALSE
              AND (slug ILIKE %s OR label ILIKE %s OR message ILIKE %s)
            ORDER BY rank DESC, views DESC
            LIMIT %s OFFSET %s;
        """, (query, f'%{query}%', f'%{query}%', f'%{query}%', per_page, offset))
        
        results = cur.fetchall()
        
        # Compter le total
        cur.execute("""
            SELECT COUNT(*) as total
            FROM badges
            WHERE official = FALSE
              AND (slug ILIKE %s OR label ILIKE %s OR message ILIKE %s);
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))
        
        total = cur.fetchone()['total']
        
        return {
            'results': results,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page
        }
        
    except Exception as e:
        logger.error(f"Error searching badges: {e}")
        return {'results': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def cleanup_old_data(days_to_keep=90):
    """Nettoie les anciennes données"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Nettoyer les logs anciens
        cur.execute("""
            DELETE FROM activity_logs 
            WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '%s days';
        """, (days_to_keep,))
        
        logs_deleted = cur.rowcount
        
        # Nettoyer le cache expiré
        cur.execute("SELECT cleanup_expired_cache()")
        cache_deleted = cur.fetchone()['cleanup_expired_cache']
        
        # Nettoyer les rate limits anciens
        cur.execute("""
            DELETE FROM rate_limits 
            WHERE last_request < CURRENT_TIMESTAMP - INTERVAL '24 hours';
        """)
        
        rate_limits_deleted = cur.rowcount
        
        conn.commit()
        
        return {
            'logs_deleted': logs_deleted,
            'cache_deleted': cache_deleted,
            'rate_limits_deleted': rate_limits_deleted
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up old data: {e}")
        if conn:
            conn.rollback()
        return {'logs_deleted': 0, 'cache_deleted': 0, 'rate_limits_deleted': 0}
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def add_favorite(badge_slug, ip_address):
    """Ajoute un badge aux favoris"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO favorites (badge_slug, ip_address)
            VALUES (%s, %s)
            ON CONFLICT (badge_slug, ip_address) DO NOTHING
            RETURNING id;
        """, (badge_slug, ip_address))
        
        result = cur.fetchone()
        conn.commit()
        
        return result is not None
        
    except Exception as e:
        logger.error(f"Error adding favorite: {e}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def remove_favorite(badge_slug, ip_address):
    """Retire un badge des favoris"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            DELETE FROM favorites
            WHERE badge_slug = %s AND ip_address = %s;
        """, (badge_slug, ip_address))
        
        deleted = cur.rowcount
        conn.commit()
        
        return deleted > 0
        
    except Exception as e:
        logger.error(f"Error removing favorite: {e}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def get_user_favorites(ip_address):
    """Récupère les favoris d'un utilisateur"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT b.slug, b.label, b.message, b.color, b.views, f.created_at
            FROM favorites f
            JOIN badges b ON f.badge_slug = b.slug
            WHERE f.ip_address = %s
            ORDER BY f.created_at DESC;
        """, (ip_address,))
        
        return cur.fetchall()
        
    except Exception as e:
        logger.error(f"Error getting favorites: {e}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

def export_badges(format='json'):
    """Exporte tous les badges"""
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT slug, label, message, color, logo_base64, 
                   views, created_at, updated_at, metadata
            FROM badges
            WHERE official = FALSE
            ORDER BY created_at DESC;
        """)
        
        badges = cur.fetchall()
        
        if format == 'json':
            import json
            return json.dumps(badges, default=str, indent=2)
        elif format == 'csv':
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=badges[0].keys() if badges else [])
            writer.writeheader()
            writer.writerows(badges)
            
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported format: {format}")
        
    except Exception as e:
        logger.error(f"Error exporting badges: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            return_db(conn)

# Initialisation automatique
if __name__ == "__main__":
    init_db()
    logger.info("Database module initialized")
