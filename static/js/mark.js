// Tap-to-save for the marking page. Each .mark-cell shows one
// competency's state. Tapping cycles it and saves the new state.

const NEXT_STATE = {
    blank: 'achieved',
    achieved: 'cooling_off',
    cooling_off: 'blank',
};

const STATE_EMOJI = {
    blank: '🔲',
    achieved: '✅',
    cooling_off: '⚠️',
};

document.addEventListener('click', async function (event) {
    // Find the cell that was tapped (or bail if the tap missed one).
    const cell = event.target.closest('.mark-cell');
    if (!cell) return;

    // Work out the next state and where to save it.
    const next = NEXT_STATE[cell.dataset.state];
    const url = `/save/${cell.dataset.student}/${cell.dataset.competency}/${next}`;

    try {
        const response = await fetch(url, { method: 'POST' });
        if (!response.ok) {
            throw new Error('Save failed: ' + response.status);
        }
        // Only update the display once the server confirmed the save.
        cell.dataset.state = next;
        cell.textContent = STATE_EMOJI[next];
    } catch (error) {
        console.error(error);
        alert('Could not save that change. Check the server and try again.');
    }
});
