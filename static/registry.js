document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;

    const status = button.parentElement.querySelector('.registry-copy-status');
    try {
        await navigator.clipboard.writeText(button.dataset.copy);
        status.textContent = 'Copied';
    } catch (error) {
        status.textContent = 'Copy unavailable';
        console.error('Could not copy install command:', error);
    }
});
