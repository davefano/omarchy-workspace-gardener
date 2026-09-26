// Pure accounting model shared by the shell and Node's regression tests.
function dayKey(now) {
    var d = new Date(now);
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}

function restore(raw, instance, ids, now) {
    var state = {version: 1, instance: instance, day: dayKey(now), seconds: {}};
    if (raw && raw.version === 1 && raw.instance === instance && raw.day === state.day) {
        ids.forEach(function(id) {
            var value = raw.seconds && raw.seconds[String(id)];
            if (id > 0 && typeof value === 'number' && isFinite(value) && value >= 0)
                state.seconds[String(id)] = value;
        });
    }
    return state;
}

function account(state, id, elapsedMs, now, active) {
    var today = dayKey(now);
    var midnight = new Date(now);
    midnight.setHours(0, 0, 0, 0);
    if (state.day !== today) {
        state.day = today;
        state.seconds = {};
    }
    // ElapsedTimer is monotonic and excludes suspend. Wall time only defines today.
    var seconds = Math.max(0, Math.min(elapsedMs, now - midnight.getTime())) / 1000;
    if (active && id > 0 && isFinite(seconds))
        state.seconds[String(id)] = (state.seconds[String(id)] || 0) + seconds;
}

function remap(state, mapping) {
    var next = {};
    Object.keys(state.seconds).forEach(function(id) {
        var target = Object.prototype.hasOwnProperty.call(mapping, id) ? mapping[id] : id;
        next[String(target)] = state.seconds[id];
    });
    state.seconds = next;
}

if (typeof module !== 'undefined') module.exports = {dayKey: dayKey, restore: restore, account: account, remap: remap};
