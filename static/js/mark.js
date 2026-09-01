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
        // The server replies with every result this student now has, because one tap
        // can change several. Passing a competency credits everything it covers, and
        // undoing it takes those credits back. Repainting only the group that was
        // clicked left the credited ones reading "Not assessed" until a reload, so the
        // feature worked and was invisible.
        const states = await response.json();
        document.querySelectorAll('.mark-btn').forEach(function (other) {
            const state = states[other.dataset.competency] || 'unassessed';
            const active = (other.dataset.state === state);
            other.classList.toggle('is-active', active);
            other.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    } catch (error) {
        console.error(error);
        alert('Could not save that change. Check the server and try again.');
    }
});
