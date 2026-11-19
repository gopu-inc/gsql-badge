const avatarInput = document.getElementById('profileAvatar');
const avatarPreview = document.querySelector('.avatar-preview');
const avatarStatus = document.getElementById('avatarStatus');
let previewUrl;

if (avatarInput && avatarPreview && avatarStatus) {
    avatarInput.addEventListener('change', () => {
        const [file] = avatarInput.files || [];
        if (!file) return;

        if (file.size > 4 * 1024 * 1024) {
            avatarInput.value = '';
            avatarStatus.textContent = 'This image exceeds the 4 MB limit.';
            return;
        }

        const allowedTypes = ['image/png', 'image/jpeg', 'image/webp'];
        if (!allowedTypes.includes(file.type)) {
            avatarInput.value = '';
            avatarStatus.textContent = 'Choose a PNG, JPEG, or WebP image.';
            return;
        }

        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = URL.createObjectURL(file);

        const image = document.createElement('img');
        image.className = 'avatar-image';
        image.alt = 'Selected profile photo preview';
        image.src = previewUrl;
        avatarPreview.replaceChildren(image);
        avatarStatus.textContent = `${file.name} selected`;
    });
}

window.addEventListener('pagehide', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
});
