import base64
from io import BytesIO
from PIL import Image
import re

def validate_image_file(file_stream):
    """Valide qu'un fichier est une image valide"""
    try:
        # Vérifier la taille du fichier (max 2MB)
        content = file_stream.read(1024 * 1024 * 2 + 1)  # Lire 2MB + 1 byte
        if len(content) > 2 * 1024 * 1024:  # 2MB
            return False
        
        # Vérifier que c'est une image valide
        file_stream.seek(0)
        try:
            img = Image.open(BytesIO(content))
            img.verify()  # Vérifie l'intégrité du fichier
            return True
        except:
            return False
            
    except Exception:
        return False
    finally:
        file_stream.seek(0)

def image_to_base64(file):
    """Convertit une image en base64 de manière sécurisée"""
    if not file:
        return None
    
    try:
        # Validation du fichier
        if not validate_image_file(file.stream):
            return None
        
        # Réinitialiser la position du fichier
        file.seek(0)
        
        # Lire et encoder
        content = file.read()
        
        # Vérification supplémentaire du type MIME
        if content[:4] == b'\x89PNG':
            mime_type = 'image/png'
        elif content[:3] == b'\xff\xd8\xff':
            mime_type = 'image/jpeg'
        elif content[:6] in (b'GIF87a', b'GIF89a'):
            mime_type = 'image/gif'
        elif content[:4] == b'<svg' or b'<svg' in content[:100]:
            mime_type = 'image/svg+xml'
        elif content[:4] == b'\x00\x00\x01\x00':
            mime_type = 'image/x-icon'
        else:
            return None
        
        # Encoder en base64
        encoded = base64.b64encode(content).decode('utf-8')
        
        # Retourner avec le préfixe data URI
        return f"data:{mime_type};base64,{encoded}"
        
    except Exception:
        return None
