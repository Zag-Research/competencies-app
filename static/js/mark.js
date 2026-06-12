// Tap-to-save for the marking page. Each competency has a group of
// state buttons (.mark-btn). Tapping one sets that state and saves it.

document.addEventListener('click', async function (event) {
    // Find the state button that was tapped (or bail if the tap missed one).
    const btn = event.target.closest('.mark-btn');
    if (!btn) return;

    // Already the active state? Nothing to save.
    if (btn.classList.contains('is-active')) return;

    const url = `/save/${btn.dataset.student}/${btn.dataset.competency}/${btn.dataset.state}`;

    try {
        const response = await fetch(url, { method: 'POST' });
        if (!response.ok) {
            throw new Error('Save failed: ' + response.status);
        }
        // Move the active highlight to the clicked button, within its group.
        const group = btn.closest('.mark-group');
        group.querySelectorAll('.mark-btn').forEach(function (other) {
            const active = (other === btn);
            other.classList.toggle('is-active', active);
            other.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    } catch (error) {
        console.error(error);
        alert('Could not save that change. Check the server and try again.');
    }
});
