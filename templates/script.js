const API_URL = 'https://zenv-hub.onrender.com/api';
const DOWNLOAD_URL = 'https://zenv-hub.onrender.com/package/download';

let authToken = null;

// =============================
// DOM Elements
// =============================
const mobileMenuToggle = document.querySelector('.mobile-menu-toggle');
const nav = document.querySelector('.nav');
const packageSearchInput = document.getElementById('package-search');
const searchButton = document.getElementById('search-button');
const packageListDiv = document.getElementById('package-list');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginErrorP = document.getElementById('login-error');
const registerErrorP = document.getElementById('register-error');
const notificationContainer = document.querySelector('.notification-container');

// =============================
// Utility Functions
// =============================

function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.textContent = message;
  notificationContainer.appendChild(notification);

  // Trigger the show animation
  setTimeout(() => {
    notification.classList.add('show');
  }, 10);

  // Remove notification after 5 seconds
  setTimeout(() => {
    notification.classList.remove('show');
    notification.addEventListener('transitionend', () => {
      if (notificationContainer.contains(notification)) {
        notificationContainer.removeChild(notification);
      }
    });
  }, 5000);
}

function setAuthToken(token) {
  authToken = token;
  if (token) {
    localStorage.setItem('authToken', token);
    // Update UI to show logged in state
    const authNavLink = document.querySelector('.nav-link[href="#auth"]');
    if (authNavLink) {
      authNavLink.textContent = 'Logout';
      authNavLink.onclick = handleLogout;
      authNavLink.removeAttribute('href'); // Remove href to prevent scrolling
    }
    // Optionally hide auth forms
    const authSection = document.getElementById('auth');
    if (authSection) {
      authSection.style.display = 'none';
    }
  } else {
    localStorage.removeItem('authToken');
    // Update UI to show logged out state
    const authNavLink = document.querySelector('.nav-link[href="#auth"]');
    if (authNavLink) {
      authNavLink.textContent = 'Auth';
      authNavLink.setAttribute('href', '#auth'); // Restore href
      authNavLink.onclick = () => scrollToSection('#auth');
    }
    // Show auth forms
    const authSection = document.getElementById('auth');
    if (authSection) {
      authSection.style.display = 'block';
    }
  }
}

function getAuthToken() {
  return localStorage.getItem('authToken');
}

function scrollToSection(id) {
  const targetElement = document.querySelector(id);
  if (targetElement) {
    const headerHeight = document.querySelector('.header')?.offsetHeight || 0;
    const offsetTop = targetElement.offsetTop - headerHeight - 20; // Add a small offset
    window.scrollTo({
      top: offsetTop,
      behavior: 'smooth'
    });
    // Close mobile menu if open
    if (nav && nav.classList.contains('mobile-open')) {
      nav.classList.remove('mobile-open');
      mobileMenuToggle.classList.remove('active');
    }
  }
}

function renderPackageCard(pkg) {
  const card = document.createElement('div');
  card.className = 'package-card';
  card.innerHTML = `
    <h3>${pkg.name}</h3>
    <p>${pkg.description || 'No description available.'}</p>
    <div class="package-meta">
      <div>Version: <span>${pkg.version}</span></div>
      <div>Author: <span>${pkg.author || 'N/A'}</span></div>
    </div>
    <a href="${DOWNLOAD_URL}/${pkg.scope ? pkg.scope + '/' : ''}${pkg.name}/${pkg.version}" class="download-button" target="_blank" rel="noopener noreferrer" aria-label="Download ${pkg.name} version ${pkg.version}">Download</a>
  `;
  return card;
}

function displayPackages(packages) {
  packageListDiv.innerHTML = ''; // Clear existing content
  if (!packages || packages.length === 0) {
    packageListDiv.innerHTML = '<p class="loading-message">No packages found matching your query.</p>';
    return;
  }
  packages.forEach(pkg => {
    packageListDiv.appendChild(renderPackageCard(pkg));
  });
}

function displayLoading(message = 'Loading packages...') {
  packageListDiv.innerHTML = `<p class="loading-message">${message}</p>`;
}

function displayError(message = 'An error occurred.') {
  packageListDiv.innerHTML = `<p class="error-message">Error: ${message}</p>`;
}

// =============================
// API Interaction Functions
// =============================

async function fetchPackages(query = '') {
  displayLoading();
  try {
    const url = query ? `${API_URL}/package/search?q=${encodeURIComponent(query)}` : `${API_URL}/package/search`;
    const response = await fetch(url);
    if (!response.ok) {
      let errorMsg = `HTTP error! status: ${response.status}`;
      try {
        const errorData = await response.json();
        errorMsg = errorData.error || errorMsg;
      } catch (e) {
        // Ignore if response is not JSON
      }
      throw new Error(errorMsg);
    }
    const data = await response.json();
    displayPackages(data.results);
  } catch (error) {
    console.error('Error fetching packages:', error);
    displayError(error.message);
  }
}

async function handleLogin(event) {
  event.preventDefault();
  loginErrorP.textContent = '';
  clearFormErrors(loginForm);

  const usernameInput = document.getElementById('login-username');
  const passwordInput = document.getElementById('login-password');

  if (!loginForm.checkValidity()) {
    showFormErrors(loginForm);
    return;
  }

  const username = usernameInput.value;
  const password = passwordInput.value;

  try {
    const response = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, password })
    });

    if (!response.ok) {
      let errorMsg = 'Login failed. Please check your credentials.';
      try {
        const errorData = await response.json();
        errorMsg = errorData.error || errorMsg;
      } catch (e) {}
      throw new Error(errorMsg);
    }

    const data = await response.json();
    setAuthToken(data.token);
    showNotification('Login successful!', 'success');
    event.target.reset();
    fetchPackages(); // Refresh list
  } catch (error) {
    loginErrorP.textContent = error.message;
    showNotification(error.message, 'error');
    console.error('Login error:', error);
  }
}

async function handleRegister(event) {
  event.preventDefault();
  registerErrorP.textContent = '';
  clearFormErrors(registerForm);

  const usernameInput = document.getElementById('register-username');
  const passwordInput = document.getElementById('register-password');

  if (!registerForm.checkValidity()) {
    showFormErrors(registerForm);
    return;
  }

  const username = usernameInput.value;
  const password = passwordInput.value;

  try {
    const response = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, password })
    });

    if (!response.ok) {
      let errorMsg = 'Registration failed. Please try again.';
      try {
        const errorData = await response.json();
        errorMsg = errorData.error || errorMsg;
      } catch (e) {}
      throw new Error(errorMsg);
    }

    const data = await response.json();
    setAuthToken(data.token);
    showNotification('Registration successful! You are now logged in.', 'success');
    event.target.reset();
    fetchPackages(); // Refresh list
  } catch (error) {
    registerErrorP.textContent = error.message;
    showNotification(error.message, 'error');
    console.error('Registration error:', error);
  }
}

function handleLogout() {
  setAuthToken(null);
  showNotification('You have been logged out.');
  fetchPackages(); 
}

// Form Validation Helper Functions
function clearFormErrors(form) {
  form.querySelectorAll('.form-error').forEach(el => el.textContent = '');
  form.querySelectorAll('input').forEach(input => input.classList.remove('input-error'));
}

function showFormErrors(form) {
  form.querySelectorAll('input[required]').forEach(input => {
    if (!input.value) {
      const errorId = input.getAttribute('aria-describedby');
      if (errorId) {
        const errorElement = document.getElementById(errorId);
        if (errorElement) {
          errorElement.textContent = `${input.labels[0]?.textContent || 'Field'} is required.`;
        }
      }
      input.classList.add('input-error');
    }
  });
}

// =============================
// Event Listeners
// =============================

document.addEventListener('DOMContentLoaded', () => {
  // Initialize Auth Token
  const token = getAuthToken();
  if (token) {
    setAuthToken(token);
  }

  // Initialize Menu Events
  if (mobileMenuToggle && nav) {
    mobileMenuToggle.addEventListener('click', () => {
      nav.classList.toggle('mobile-open');
      mobileMenuToggle.classList.toggle('active');
    });
  }

  // Close mobile menu when clicking outside
  ['click', 'touchstart'].forEach(evt => {
    document.addEventListener(evt, function(e) {
      if (nav && !nav.contains(e.target) && !mobileMenuToggle.contains(e.target)) {
        nav.classList.remove('mobile-open');
        mobileMenuToggle.classList.remove('active');
      }
    });
  });

  // Navigation Link Click Behavior
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', function(e) {
      const href = this.getAttribute('href');
      if (href && href.startsWith('#')) {
        e.preventDefault();
        // If it's the auth link and user is logged in, treat as logout
        if (href === '#auth' && authToken) {
          handleLogout();
          return;
        }
        scrollToSection(href);
      } else if (href && href.startsWith('http')) {
        // Handle external links if any
        window.open(href, '_blank');
      }
    });
  });

  // Search Button Event
  searchButton.addEventListener('click', () => {
    const query = packageSearchInput.value;
    fetchPackages(query);
  });

  // Search Input Enter Key Event
  packageSearchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault(); // Prevent default form submission if inside a form
      searchButton.click();
    }
  });

  // Form Submit Events
  if (loginForm) {
    loginForm.addEventListener('submit', handleLogin);
  }
  if (registerForm) {
    registerForm.addEventListener('submit', handleRegister);
  }

  // Initial package load
  fetchPackages();
});
