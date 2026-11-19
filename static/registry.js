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

const dependencyPanel = document.querySelector('[data-dependencies-url]');
if (dependencyPanel) {
    const status = dependencyPanel.querySelector('[data-dependencies-status]');
    const content = dependencyPanel.querySelector('[data-dependencies-content]');

    fetch(dependencyPanel.dataset.dependenciesUrl, {
        headers: { Accept: 'application/json' }
    })
        .then((response) => {
            if (!response.ok) throw new Error(`Dependency request failed (${response.status})`);
            return response.json();
        })
        .then((data) => {
            if (data.error) throw new Error(data.error);

            let total = 0;
            for (const group of ['dependencies', 'dev_dependencies']) {
                const items = Array.isArray(data[group]) ? data[group] : [];
                const section = dependencyPanel.querySelector(`[data-dependency-section="${group}"]`);
                const list = dependencyPanel.querySelector(`[data-dependency-list="${group}"]`);
                section.hidden = items.length === 0;
                total += items.length;

                for (const item of items) {
                    const row = document.createElement('li');
                    const name = document.createElement('span');
                    const version = document.createElement('code');
                    name.textContent = String(item.name || 'Unknown package');
                    version.textContent = String(item.version || '*');
                    row.append(name, version);
                    list.append(row);
                }
            }

            content.hidden = total === 0;
            status.textContent = total === 0 ? 'No dependencies declared for this version.' : '';
        })
        .catch((error) => {
            status.textContent = 'Could not load dependencies. Try refreshing the page.';
            console.error('Could not load package dependencies:', error);
        });
}
