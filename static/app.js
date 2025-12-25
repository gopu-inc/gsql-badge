// Configuration
const API_BASE = window.location.origin;
let currentTheme = 'dark';

// Fonctions de thème
function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    localStorage.setItem('theme', currentTheme);
    
    const icon = document.querySelector('.theme-toggle i');
    icon.className = currentTheme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
}

// Initialisation du thème
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    currentTheme = savedTheme;
    document.documentElement.setAttribute('data-theme', currentTheme);
    
    const icon = document.querySelector('.theme-toggle i');
    if (icon) {
        icon.className = currentTheme === 'dark' ? 'fas fa-moon' : 'fas fa-sun';
    }
}

// Gestion des onglets
function switchTab(tabId) {
    // Désactiver tous les onglets
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    
    // Activer l'onglet sélectionné
    const activeTab = document.querySelector(`.tab[onclick="switchTab('${tabId}')"]`);
    const activeContent = document.getElementById(tabId);
    
    if (activeTab) activeTab.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
}

// Gestion du drag and drop
function initDragAndDrop() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file');
    
    if (!dropZone || !fileInput) return;
    
    // Cliquer sur la zone = cliquer sur l'input file
    dropZone.addEventListener('click', () => fileInput.click());
    
    // Gestion du drag over
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    
    // Gestion du drag leave
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    
    // Gestion du drop
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateFileNameDisplay();
        }
    });
    
    // Mise à jour de l'affichage du nom de fichier
    fileInput.addEventListener('change', updateFileNameDisplay);
}

function updateFileNameDisplay() {
    const fileInput = document.getElementById('file');
    const dropZone = document.getElementById('drop-zone');
    
    if (fileInput.files.length) {
        const file = fileInput.files[0];
        dropZone.innerHTML = `
            <i class="fas fa-check-circle fa-3x" style="margin-bottom: 1rem; color: #10b981;"></i>
            <h3>${file.name}</h3>
            <p>${(file.size / 1024).toFixed(1)} KB</p>
            <p class="small-text">Cliquez pour changer</p>
        `;
        
        // Générer un slug à partir du nom de fichier
        const slugInput = document.getElementById('upload-slug');
        if (slugInput && !slugInput.value) {
            const slug = file.name.replace(/\.[^/.]+$/, "").toLowerCase()
                .replace(/[^a-z0-9]/g, '-')
                .replace(/-+/g, '-')
                .replace(/^-|-$/g, '');
            slugInput.value = slug;
        }
    }
}

// Upload simple
async function uploadBadge() {
    const fileInput = document.getElementById('file');
    const slugInput = document.getElementById('upload-slug');
    const resultDiv = document.getElementById('upload-result');
    const loadingDiv = document.getElementById('upload-loading');
    
    if (!fileInput.files.length) {
        showError(resultDiv, '❌ Veuillez sélectionner une image');
        return;
    }
    
    const slug = slugInput.value.trim();
    if (!slug) {
        showError(resultDiv, '❌ Veuillez entrer un identifiant pour le badge');
        return;
    }
    
    // Validation du slug
    if (!/^[a-z0-9-]+$/.test(slug)) {
        showError(resultDiv, '❌ L\'identifiant ne peut contenir que des lettres minuscules, chiffres et tirets');
        return;
    }
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('slug', slug);
    
    // Afficher le loading
    loadingDiv.classList.add('active');
    resultDiv.innerHTML = '';
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Erreur lors de la création du badge');
        }
        
        showSuccess(resultDiv, data);
        
    } catch (error) {
        showError(resultDiv, `❌ ${error.message}`);
    } finally {
        loadingDiv.classList.remove('active');
    }
}

// Création avancée
async function createAdvancedBadge() {
    const slug = document.getElementById('advanced-slug').value.trim();
    const label = document.getElementById('advanced-label').value.trim();
    const message = document.getElementById('advanced-message').value.trim();
    const color = document.getElementById('advanced-color').value.trim();
    const fileInput = document.getElementById('advanced-file');
    const logoUrl = document.getElementById('advanced-logo-url').value.trim();
    const resultDiv = document.getElementById('advanced-result');
    const loadingDiv = document.getElementById('advanced-loading');
    
    if (!slug) {
        showError(resultDiv, '❌ Le slug est requis');
        return;
    }
    
    // Préparation des données
    const data = {
        slug: slug,
        label: label || 'Custom',
        message: message || slug,
        color: color || '#22c55e'
    };
    
    // Ajouter le logo si fourni
    if (logoUrl) {
        data.logo_url = logoUrl;
    } else if (fileInput.files.length) {
        // Convertir le fichier en base64
        const base64 = await fileToBase64(fileInput.files[0]);
        if (base64) {
            data.logo_base64 = base64.split(',')[1]; // Enlever le préfixe
        }
    }
    
    // Afficher le loading
    loadingDiv.classList.add('active');
    resultDiv.innerHTML = '';
    
    try {
        const response = await fetch('/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Erreur lors de la création du badge');
        }
        
        showSuccess(resultDiv, result);
        
    } catch (error) {
        showError(resultDiv, `❌ ${error.message}`);
    } finally {
        loadingDiv.classList.remove('active');
    }
}

// Test de l'API
async function testAPI() {
    const jsonInput = document.getElementById('api-test-json');
    const resultDiv = document.getElementById('api-test-result');
    
    let data;
    try {
        data = JSON.parse(jsonInput.value);
    } catch (e) {
        showError(resultDiv, '❌ JSON invalide');
        return;
    }
    
    resultDiv.innerHTML = '<div class="loading"><div class="spinner"></div><p>Test en cours...</p></div>';
    
    try {
        const response = await fetch('/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Erreur API');
        }
        
        resultDiv.innerHTML = `
            <div style="background: linear-gradient(135deg, #10b98120, #10b98110); border: 1px solid #10b981; border-radius: 8px; padding: 1rem;">
                <h4 style="margin-top: 0; color: #10b981;"><i class="fas fa-check-circle"></i> Succès !</h4>
                <pre style="background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 6px; overflow-x: auto;">${JSON.stringify(result, null, 2)}</pre>
                ${result.badge_url ? `<img src="${result.badge_url}" alt="Badge test" style="margin: 1rem 0; height: 20px;">` : ''}
            </div>
        `;
        
    } catch (error) {
        resultDiv.innerHTML = `
            <div style="background: linear-gradient(135deg, #ef444420, #ef444410); border: 1px solid #ef4444; border-radius: 8px; padding: 1rem;">
                <h4 style="margin-top: 0; color: #ef4444;"><i class="fas fa-times-circle"></i> Erreur</h4>
                <p>${error.message}</p>
            </div>
        `;
    }
}

// Helper: Convertir fichier en base64
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = () => resolve(reader.result);
        reader.onerror = error => reject(error);
    });
}

// Helper: Afficher un succès
function showSuccess(container, data) {
    const badgeUrl = data.badge_url || `${API_BASE}/badge/${data.slug}`;
    
    container.innerHTML = `
        <div style="background: linear-gradient(135deg, #10b98120, #10b98110); border: 1px solid #10b981; border-radius: 12px; padding: 1.5rem; margin: 1rem 0;">
            <h3 style="margin-top: 0; color: #10b981;"><i class="fas fa-check-circle"></i> Badge créé avec succès !</h3>
            
            <div style="display: flex; align-items: center; gap: 1rem; margin: 1rem 0; flex-wrap: wrap;">
                <img src="${badgeUrl}" alt="${data.label}" style="height: 30px; border-radius: 4px;">
                <div>
                    <strong>${data.label}: ${data.message}</strong><br>
                    <a href="${badgeUrl}" target="_blank">${badgeUrl}</a>
                </div>
            </div>
            
            <div class="tabs" style="margin: 1rem 0;">
                <button class="tab active" onclick="switchCodeTab(this, 'markdown')">Markdown</button>
                <button class="tab" onclick="switchCodeTab(this, 'html')">HTML</button>
                <button class="tab" onclick="switchCodeTab(this, 'direct')">URL directe</button>
            </div>
            
            <div id="markdown-code" class="code-tab active">
                <pre class="code"><code>![${data.label}: ${data.message}](${badgeUrl})</code></pre>
            </div>
            
            <div id="html-code" class="code-tab">
                <pre class="code"><code>&lt;img src="${badgeUrl}" alt="${data.label}: ${data.message}"&gt;</code></pre>
            </div>
            
            <div id="direct-code" class="code-tab">
                <pre class="code"><code>${badgeUrl}</code></pre>
            </div>
            
            <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
                <button onclick="copyToClipboard('![${data.label}: ${data.message}](${badgeUrl})')" class="btn" style="flex: 1;">
                    <i class="fas fa-copy"></i> Copier Markdown
                </button>
                <button onclick="window.open('${badgeUrl}', '_blank')" class="btn" style="flex: 1;">
                    <i class="fas fa-external-link-alt"></i> Ouvrir
                </button>
            </div>
        </div>
    `;
    
    // Faire défiler jusqu'au résultat
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Helper: Afficher une erreur
function showError(container, message) {
    container.innerHTML = `
        <div style="background: linear-gradient(135deg, #ef444420, #ef444410); border: 1px solid #ef4444; border-radius: 12px; padding: 1.5rem; margin: 1rem 0;">
            <h3 style="margin-top: 0; color: #ef4444;"><i class="fas fa-exclamation-triangle"></i> Erreur</h3>
            <p style="margin: 0;">${message}</p>
        </div>
    `;
    
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Helper: Basculer entre les onglets de code
function switchCodeTab(button, tabId) {
    const tabs = button.parentElement.querySelectorAll('.tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    button.classList.add('active');
    
    const codeTabs = button.parentElement.parentElement.querySelectorAll('.code-tab');
    codeTabs.forEach(tab => tab.classList.remove('active'));
    document.getElementById(`${tabId}-code`).classList.add('active');
}

// Helper: Copier dans le presse-papier
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Afficher une notification
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #10b981;
            color: white;
            padding: 1rem;
            border-radius: 8px;
            z-index: 1000;
            animation: slideIn 0.3s;
        `;
        notification.innerHTML = '<i class="fas fa-check"></i> Copié dans le presse-papier !';
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s';
            setTimeout(() => notification.remove(), 300);
        }, 2000);
    });
}

// Initialisation des couleurs
function initColorPicker() {
    const colorPicker = document.getElementById('advanced-color-picker');
    const colorInput = document.getElementById('advanced-color');
    const colorPreview = document.getElementById('color-preview');
    
    if (!colorPicker || !colorInput || !colorPreview) return;
    
    function updateColor() {
        const color = colorInput.value;
        colorPicker.value = color;
        colorPreview.style.backgroundColor = color;
    }
    
    colorInput.addEventListener('input', updateColor);
    colorPicker.addEventListener('input', (e) => {
        colorInput.value = e.target.value;
        updateColor();
    });
    
    updateColor();
}

// Charger des exemples dynamiques
async function loadBadgeExamples() {
    const exampleContainer = document.getElementById('custom-badge-example');
    if (!exampleContainer) return;
    
    // Exemple de badge personnalisé
    const exampleData = {
        slug: 'example',
        label: 'Example',
        message: 'Custom Badge',
        color: '#8b5cf6'
    };
    
    try {
        // Créer un badge exemple
        const response = await fetch('/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(exampleData)
        });
        
        if (response.ok) {
            const data = await response.json();
            exampleContainer.innerHTML = `
                <img src="${data.badge_url}" alt="Badge exemple" class="badge-preview-large">
            `;
            
            // Mettre à jour le code d'exemple
            const codeElement = document.getElementById('custom-badge-code');
            if (codeElement) {
                codeElement.querySelector('code').textContent = 
                    `![${data.label}](${data.badge_url})`;
            }
        }
    } catch (error) {
        console.log('Could not load example badge:', error);
    }
}

// Compteur de visiteurs (simulé)
function updateVisitorCount() {
    const countElement = document.getElementById('visitor-count');
    if (!countElement) return;
    
    // Récupérer depuis localStorage ou générer un nombre aléatoire
    let count = localStorage.getItem('visitor_count');
    if (!count) {
        count = Math.floor(Math.random() * 1000) + 500;
        localStorage.setItem('visitor_count', count);
    } else {
        count = parseInt(count) + 1;
        localStorage.setItem('visitor_count', count);
    }
    
    // Formater avec des séparateurs de milliers
    countElement.textContent = count.toLocaleString();
}

// Initialisation au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    initTheme();
    initDragAndDrop();
    initColorPicker();
    loadBadgeExamples();
    updateVisitorCount();
    
    // Activer le premier onglet
    switchTab('upload-tab');
    
    // Animation des cartes
    const cards = document.querySelectorAll('.badge-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.1}s`;
    });
});
