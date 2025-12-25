def generate_badge_svg(label, message, color, logo_base64=None):
    # Calcul dynamique des largeurs basé sur la longueur du texte
    label_width = len(label) * 7 + 40  # Approximation de la largeur du texte
    message_width = len(message) * 7 + 40
    total_width = label_width + message_width
    
    # Position du message dépend de la largeur du label
    message_x = label_width
    logo_space = 34 if logo_base64 else 10
    
    logo_svg = ""
    if logo_base64:
        logo_svg = f'''
        <image x="10" y="8" width="16" height="16"
               href="data:image/png;base64,{logo_base64}"
               preserveAspectRatio="xMidYMid meet"/>
        '''
    
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {message}">
  <defs>
    <linearGradient id="grad" x2="0" y2="100%">
      <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
      <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <clipPath id="round-corner">
      <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
    </clipPath>
  </defs>
  
  <g clip-path="url(#round-corner)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{message_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#grad)"/>
  </g>
  
  {logo_svg}
  
  <g fill="#fff" text-anchor="middle" font-family="'DejaVu Sans','Verdana','Arial',sans-serif" font-size="11">
    <text x="{logo_space + (label_width - logo_space)/2}" y="15" fill="#fff">
      {label}
    </text>
    <text x="{message_x + message_width/2}" y="15" fill="#fff">
      {message}
    </text>
  </g>
</svg>
"""
