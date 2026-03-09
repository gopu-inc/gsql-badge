class BadgeGenerator:
    @staticmethod
    def generate(label, value, color='blue'):
        colors = {
            'blue': '#007ec6',
            'green': '#4c1',
            'red': '#e05d44',
            'orange': '#fe7d37',
            'yellow': '#dfb317',
            'purple': '#9f5f9f',
            'pink': '#ff69b4',
            'gray': '#9f9f9f',
            'lightgray': '#aaa',
            'cyan': '#1ba8b0',
            'black': '#333'
        }
        
        hex_color = colors.get(color.lower(), colors['blue'])
        
        # Calculer les dimensions
        label_len = len(label)
        value_len = len(value)
        label_width = max(label_len * 7 + 10, 40)
        value_width = max(value_len * 7 + 10, 40)
        total_width = label_width + value_width
        
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img">
            <linearGradient id="s" x2="0" y2="100%">
                <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
                <stop offset="1" stop-opacity=".1"/>
            </linearGradient>
            <clipPath id="r">
                <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
            </clipPath>
            <g clip-path="url(#r)">
                <rect width="{label_width}" height="20" fill="#555"/>
                <rect x="{label_width}" width="{value_width}" height="20" fill="{hex_color}"/>
                <rect width="{total_width}" height="20" fill="url(#s)"/>
            </g>
            <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
                <text x="{label_width//2}" y="14">{label}</text>
                <text x="{label_width + value_width//2}" y="14">{value}</text>
            </g>
        </svg>'''
