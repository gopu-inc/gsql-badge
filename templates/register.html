{% extends "base.html" %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8 col-lg-6">
        <div class="card">
            <div class="card-header text-center">
                <h4 class="mb-0">
                    <i class="bi bi-person-plus me-2"></i>Créer un compte
                </h4>
            </div>
            <div class="card-body">
                <form method="POST" action="{{ url_for('register') }}" id="registerForm">
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="username" class="form-label">
                                <i class="bi bi-person me-1"></i>Nom d'utilisateur *
                            </label>
                            <input type="text" 
                                   class="form-control" 
                                   id="username" 
                                   name="username"
                                   placeholder="Choisissez un nom d'utilisateur"
                                   required
                                   minlength="3"
                                   maxlength="50">
                            <div class="form-text">3 à 50 caractères (lettres, chiffres, underscores)</div>
                        </div>
                        
                        <div class="col-md-6 mb-3">
                            <label for="email" class="form-label">
                                <i class="bi bi-envelope me-1"></i>Adresse Email *
                            </label>
                            <input type="email" 
                                   class="form-control" 
                                   id="email" 
                                   name="email"
                                   placeholder="votre@email.com"
                                   required>
                        </div>
                    </div>
                    
                    <div class="row">
                        <div class="col-md-6 mb-3">
                            <label for="password" class="form-label">
                                <i class="bi bi-lock me-1"></i>Mot de passe *
                            </label>
                            <div class="input-group">
                                <input type="password" 
                                       class="form-control" 
                                       id="password" 
                                       name="password"
                                       placeholder="Au moins 8 caractères"
                                       required
                                       minlength="8">
                                <button class="btn btn-outline-secondary" 
                                        type="button"
                                        onclick="togglePassword('password')">
                                    <i class="bi bi-eye"></i>
                                </button>
                            </div>
                            <div class="password-strength mt-1">
                                <div class="progress" style="height: 4px;">
                                    <div class="progress-bar" id="passwordStrength" style="width: 0%"></div>
                                </div>
                                <small class="text-muted" id="passwordHint"></small>
                            </div>
                        </div>
                        
                        <div class="col-md-6 mb-3">
                            <label for="confirm_password" class="form-label">
                                <i class="bi bi-lock-fill me-1"></i>Confirmer le mot de passe *
                            </label>
                            <div class="input-group">
                                <input type="password" 
                                       class="form-control" 
                                       id="confirm_password" 
                                       name="confirm_password"
                                       placeholder="Retapez votre mot de passe"
                                       required>
                                <button class="btn btn-outline-secondary" 
                                        type="button"
                                        onclick="togglePassword('confirm_password')">
                                    <i class="bi bi-eye"></i>
                                </button>
                            </div>
                            <div class="form-text" id="passwordMatch"></div>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <label class="form-label">
                            <i class="bi bi-github me-1"></i>Token GitHub (optionnel)
                        </label>
                        <input type="text" 
                               class="form-control" 
                               id="github_token" 
                               name="github_token"
                               placeholder="ghp_..."
                               aria-describedby="githubTokenHelp">
                        <div id="githubTokenHelp" class="form-text">
                            Pour synchroniser vos dépôts GitHub. Créez-en un sur <a href="https://github.com/settings/tokens" target="_blank">GitHub Settings</a>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="terms" name="terms" required>
                            <label class="form-check-label" for="terms">
                                J'accepte les <a href="#" class="text-decoration-none">conditions d'utilisation</a> 
                                et la <a href="#" class="text-decoration-none">politique de confidentialité</a>
                            </label>
                        </div>
                    </div>
                    
                    <div class="d-grid gap-2">
                        <button type="submit" class="btn btn-zenv" id="submitBtn">
                            <i class="bi bi-person-plus me-1"></i>Créer mon compte
                        </button>
                    </div>
                </form>
                
                <hr class="my-4">
                
                <div class="text-center">
                    <p class="mb-0">
                        Déjà un compte ? 
                        <a href="{{ url_for('login') }}" class="text-decoration-none">
                            Connectez-vous ici
                        </a>
                    </p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    document.addEventListener('DOMContentLoaded', function() {
        const password = document.getElementById('password');
        const confirmPassword = document.getElementById('confirm_password');
        const passwordStrength = document.getElementById('passwordStrength');
        const passwordHint = document.getElementById('passwordHint');
        const passwordMatch = document.getElementById('passwordMatch');
        
        function checkPasswordStrength(pw) {
            let strength = 0;
            let hint = '';
            
            if (pw.length >= 8) strength += 25;
            if (/[A-Z]/.test(pw)) strength += 25;
            if (/[0-9]/.test(pw)) strength += 25;
            if (/[^A-Za-z0-9]/.test(pw)) strength += 25;
            
            // Mettre à jour la barre de progression
            passwordStrength.style.width = strength + '%';
            
            // Définir la couleur et l'indice
            if (strength < 25) {
                passwordStrength.className = 'progress-bar bg-danger';
                hint = 'Très faible';
            } else if (strength < 50) {
                passwordStrength.className = 'progress-bar bg-warning';
                hint = 'Faible';
            } else if (strength < 75) {
                passwordStrength.className = 'progress-bar bg-info';
                hint = 'Moyen';
            } else {
                passwordStrength.className = 'progress-bar bg-success';
                hint = 'Fort';
            }
            
            passwordHint.textContent = hint;
        }
        
        function checkPasswordMatch() {
            if (!password.value || !confirmPassword.value) {
                passwordMatch.textContent = '';
                return;
            }
            
            if (password.value === confirmPassword.value) {
                passwordMatch.innerHTML = '<span class="text-success"><i class="bi bi-check-circle"></i> Les mots de passe correspondent</span>';
                return true;
            } else {
                passwordMatch.innerHTML = '<span class="text-danger"><i class="bi bi-x-circle"></i> Les mots de passe ne correspondent pas</span>';
                return false;
            }
        }
        
        password.addEventListener('input', function() {
            checkPasswordStrength(this.value);
            checkPasswordMatch();
        });
        
        confirmPassword.addEventListener('input', checkPasswordMatch);
        
        // Validation du formulaire
        document.getElementById('registerForm').addEventListener('submit', function(e) {
            if (!checkPasswordMatch()) {
                e.preventDefault();
                alert('Les mots de passe ne correspondent pas');
                return false;
            }
            
            if (!document.getElementById('terms').checked) {
                e.preventDefault();
                alert('Vous devez accepter les conditions d\'utilisation');
                return false;
            }
            
            return true;
        });
    });
</script>
{% endblock %}
