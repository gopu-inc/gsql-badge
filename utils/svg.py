def generate_badge_svg(label, message, color, logo_base64=None):
    logo_svg = ""
    if logo_base64:
        logo_svg = f'''
        <image x="10" y="8" width="24" height="24"
          href="data:image/png;base64,{logo_base64}" />
        '''

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="360" height="40" role="img">
  <defs>
    <linearGradient id="grad" x2="0" y2="100%">
      <stop offset="0" stop-color="#fff" stop-opacity=".15"/>
      <stop offset="1" stop-opacity=".05"/>
    </linearGradient>
  </defs>

  <rect width="140" height="40" fill="#111" rx="8"/>
  <rect x="140" width="220" height="40" fill="{color}" rx="8"/>
  <rect width="360" height="40" fill="url(#grad)" rx="8"/>

  {logo_svg}

  <text x="50" y="26" fill="#fff"
        font-family="Verdana,Arial"
        font-size="14" font-weight="bold">
    {label}
  </text>

  <text x="155" y="26" fill="#fff"
        font-family="Verdana,Arial"
        font-size="14">
    {message}
  </text>
</svg>
"""
