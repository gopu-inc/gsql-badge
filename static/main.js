// ============================================================================
// Zarch Hub - Main JavaScript
// ============================================================================

// Mobile Menu Toggle
document.addEventListener('DOMContentLoaded', function() {
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const mobileMenu = document.getElementById('mobileMenu');
    
    if (mobileMenuBtn && mobileMenu) {
        mobileMenuBtn.addEventListener('click', function() {
            mobileMenu.classList.toggle('active');
            const icon = mobileMenuBtn.querySelector('i');
            if (mobileMenu.classList.contains('active')) {
                icon.classList.remove('fa-bars');
                icon.classList.add('fa-times');
            } else {
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            }
        });
        
        // Close menu when clicking outside
        document.addEventListener('click', function(event) {
            if (!mobileMenu.contains(event.target) && !mobileMenuBtn.contains(event.target)) {
                mobileMenu.classList.remove('active');
                const icon = mobileMenuBtn.querySelector('i');
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            }
        });
    }
    
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
    
    // Initialize tooltips
    initTooltips();
    
    // Initialize copy buttons
    initCopyButtons();
    
    // Initialize search with debounce
    initSearch();
    
    // Initialize tab system
    initTabs();
});

// ============================================================================
// Tooltips
// ============================================================================

function initTooltips() {
    const tooltips = document.querySelectorAll('[data-tooltip]');
    
    tooltips.forEach(element => {
        element.addEventListener('mouseenter', function(e) {
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.textContent = this.dataset.tooltip;
            tooltip.style.position = 'absolute';
            tooltip.style.background = 'var(--dark)';
            tooltip.style.color = 'white';
            tooltip.style.padding = '0.5rem 1rem';
            tooltip.style.borderRadius = 'var(--radius-md)';
            tooltip.style.fontSize = '0.875rem';
            tooltip.style.zIndex = '10000';
            tooltip.style.pointerEvents = 'none';
            tooltip.style.whiteSpace = 'nowrap';
            
            document.body.appendChild(tooltip);
            
            const rect = this.getBoundingClientRect();
            tooltip.style.top = rect.top - tooltip.offsetHeight - 10 + 'px';
            tooltip.style.left = rect.left + (rect.width - tooltip.offsetWidth) / 2 + 'px';
            
            this.addEventListener('mouseleave', function() {
                tooltip.remove();
            }, { once: true });
        });
    });
}

// ============================================================================
// Copy Buttons
// ============================================================================

function initCopyButtons() {
    document.querySelectorAll('.btn-copy').forEach(button => {
        button.addEventListener('click', function() {
            const command = this.dataset.command || 'apkm install ' + window.location.pathname.split('/').pop();
            copyToClipboard(command);
            
            // Show success feedback
            const originalText = this.innerHTML;
            this.innerHTML = '<i class="fas fa-check"></i> Copied!';
            this.style.background = 'var(--gradient-secondary)';
            
            setTimeout(() => {
                this.innerHTML = originalText;
                this.style.background = '';
            }, 2000);
        });
    });
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showNotification('Command copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy:', err);
        showNotification('Failed to copy command', 'error');
    });
}

// ============================================================================
// Search with Debounce
// ============================================================================

function initSearch() {
    const searchInput = document.querySelector('.search-input');
    if (!searchInput) return;
    
    let searchTimeout;
    let searchResults = document.createElement('div');
    searchResults.className = 'search-results glass-effect';
    searchInput.parentElement.appendChild(searchResults);
    
    searchInput.addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        if (query.length < 2) {
            searchResults.style.display = 'none';
            return;
        }
        
        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 500);
    });
    
    // Close results when clicking outside
    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.style.display = 'none';
        }
    });
}

async function performSearch(query) {
    const searchResults = document.querySelector('.search-results');
    
    try {
        const response = await fetch(`/api/package/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        
        if (data.results && data.results.length > 0) {
            displaySearchResults(data.results);
        } else {
            searchResults.innerHTML = '<div class="search-no-results">No packages found</div>';
            searchResults.style.display = 'block';
        }
    } catch (error) {
        console.error('Search failed:', error);
        searchResults.style.display = 'none';
    }
}

function displaySearchResults(results) {
    const searchResults = document.querySelector('.search-results');
    
    let html = '';
    results.slice(0, 5).forEach(pkg => {
        html += `
            <a href="/package/${pkg.name}" class="search-result-item">
                <i class="fas fa-box"></i>
                <div class="search-result-info">
                    <div class="search-result-name">${pkg.name}</div>
                    <div class="search-result-meta">
                        <span class="search-result-version">${pkg.version}</span>
                        <span class="search-result-author">${pkg.author || 'Unknown'}</span>
                    </div>
                </div>
            </a>
        `;
    });
    
    if (results.length > 5) {
        html += `<a href="/packages?q=${encodeURIComponent(query)}" class="search-view-all">View all ${results.length} results →</a>`;
    }
    
    searchResults.innerHTML = html;
    searchResults.style.display = 'block';
}

// ============================================================================
// Tabs System
// ============================================================================

function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.dataset.tab || this.textContent.trim().toLowerCase();
            
            // Remove active class from all buttons and tabs
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Add active class to current button and tab
            this.classList.add('active');
            const activeTab = document.getElementById(tabName + '-tab');
            if (activeTab) {
                activeTab.classList.add('active');
            }
        });
    });
}

// ============================================================================
// Notifications
// ============================================================================

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `flash-message flash-${type} glass-effect`;
    notification.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
        ${message}
    `;
    
    const container = document.querySelector('.flash-messages') || document.body;
    container.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// ============================================================================
// Infinite Scroll for Packages
// ============================================================================

let currentPage = 1;
let loading = false;
let hasMore = true;

function initInfiniteScroll() {
    const packageGrid = document.querySelector('.package-grid');
    if (!packageGrid) return;
    
    window.addEventListener('scroll', () => {
        if (loading || !hasMore) return;
        
        const scrollPosition = window.innerHeight + window.scrollY;
        const threshold = document.documentElement.scrollHeight - 1000;
        
        if (scrollPosition >= threshold) {
            loadMorePackages();
        }
    });
}

async function loadMorePackages() {
    loading = true;
    currentPage++;
    
    try {
        const response = await fetch(`/api/packages?page=${currentPage}`);
        const data = await response.json();
        
        if (data.packages && data.packages.length > 0) {
            appendPackages(data.packages);
        } else {
            hasMore = false;
        }
    } catch (error) {
        console.error('Failed to load more packages:', error);
    } finally {
        loading = false;
    }
}

function appendPackages(packages) {
    const grid = document.querySelector('.package-grid');
    
    packages.forEach(pkg => {
        const card = createPackageCard(pkg);
        grid.appendChild(card);
    });
}

function createPackageCard(pkg) {
    const card = document.createElement('a');
    card.href = `/package/${pkg.name}`;
    card.className = 'package-card';
    card.setAttribute('data-aos', 'fade-up');
    
    card.innerHTML = `
        <div class="package-header">
            <i class="fas fa-box"></i>
            <h3>${pkg.name}</h3>
            <span class="badge ${pkg.scope}">${pkg.scope}</span>
        </div>
        <div class="package-body">
            <p class="package-description">${pkg.description || 'No description'}</p>
            <div class="package-meta">
                <span class="version"><i class="fas fa-tag"></i> ${pkg.version}</span>
                <span class="author"><i class="fas fa-user"></i> ${pkg.author || 'Unknown'}</span>
            </div>
            <div class="package-stats">
                <span><i class="fas fa-download"></i> ${pkg.downloads || 0}</span>
                <span><i class="fas fa-calendar"></i> ${pkg.created_at ? pkg.created_at.slice(0, 10) : 'N/A'}</span>
            </div>
        </div>
    `;
    
    return card;
}

// ============================================================================
// Package Version Selector
// ============================================================================

function initVersionSelector() {
    const selector = document.querySelector('.version-selector');
    if (!selector) return;
    
    selector.addEventListener('change', function() {
        const version = this.value;
        const name = this.dataset.package;
        window.location.href = `/package/${name}?version=${version}`;
    });
}

// ============================================================================
// Dark Mode Toggle
// ============================================================================

function initDarkMode() {
    const darkModeToggle = document.getElementById('darkModeToggle');
    if (!darkModeToggle) return;
    
    // Check for saved preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const savedMode = localStorage.getItem('darkMode');
    
    if (savedMode === 'true' || (!savedMode && prefersDark)) {
        document.body.classList.add('dark-mode');
        updateDarkModeIcon(true);
    }
    
    darkModeToggle.addEventListener('click', function() {
        const isDark = document.body.classList.toggle('dark-mode');
        localStorage.setItem('darkMode', isDark);
        updateDarkModeIcon(isDark);
    });
}

function updateDarkModeIcon(isDark) {
    const icon = document.querySelector('#darkModeToggle i');
    if (icon) {
        icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    }
}

// ============================================================================
// Initialize everything when DOM is ready
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initInfiniteScroll();
    initVersionSelector();
    initDarkMode();
    
    // Add animation on scroll
    const animatedElements = document.querySelectorAll('[data-aos]');
    if (animatedElements.length > 0 && typeof AOS !== 'undefined') {
        AOS.refresh();
    }
});

// ============================================================================
// Export functions for global use
// ============================================================================

window.copyInstallCommand = copyToClipboard;
window.showNotification = showNotification;
window.showTab = function(tabName) {
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(tabName + '-tab').classList.add('active');
};
