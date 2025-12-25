import re
import html

def clean_slug(text):
    """Nettoie un slug pour être sûr"""
    if not text or not isinstance(text, str):
        return ""
    
    # Nettoyage de base
    text = text.strip().lower()
    
    # Remplacement des caractères spéciaux par des tirets
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    
    # Suppression des tirets au début et à la fin
    text = text.strip('-')
    
    # Limite de longueur
    if len(text) > 100:
        text = text[:100]
    
    # Vérification finale
    if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]?$', text):
        return "badge"
    
    return text

def sanitize_text(text, max_length=100):
    """Nettoie le texte pour éviter les injections XSS"""
    if not text or not isinstance(text, str):
        return ""
    
    # Échappement HTML
    text = html.escape(text.strip())
    
    # Limite de longueur
    if len(text) > max_length:
        text = text[:max_length] + "..."
    
    # Suppression des caractères de contrôle
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    
    return text

def validate_color(color):
    """Valide et nettoie une couleur hexadécimale"""
    if not color or not isinstance(color, str):
        return "#22c55e"
    
    color = color.strip().lower()
    
    # Format hexadécimal
    hex_pattern = r'^#([a-f0-9]{3}|[a-f0-9]{6})$'
    
    if re.match(hex_pattern, color):
        return color
    
    # Noms de couleurs CSS sécurisés
    safe_colors = {
        'red': '#dc2626',
        'green': '#16a34a',
        'blue': '#2563eb',
        'yellow': '#ca8a04',
        'purple': '#9333ea',
        'pink': '#db2777',
        'gray': '#6b7280',
        'black': '#000000',
        'white': '#ffffff',
        'orange': '#ea580c',
    }
    
    if color in safe_colors:
        return safe_colors[color]
    
    # Retourne une couleur par défaut si invalide
    return "#22c55e"

def is_safe_filename(filename):
    """Vérifie si un nom de fichier est sûr"""
    if not filename:
        return False
    
    # Vérification des extensions
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'}
    
    # Vérification des chemins
    if '..' in filename or '/' in filename or '\\' in filename:
        return False
    
    # Vérification de l'extension
    ext = filename.lower()
    for allowed in allowed_extensions:
        if ext.endswith(allowed):
            return True
    
    return False
