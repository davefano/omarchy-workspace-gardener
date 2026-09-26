const {test} = require('node:test');
const assert = require('node:assert/strict');
const M = require('./Model.js');
const now = new Date(2026, 8, 26, 12).getTime();
test('counts only the prior focused interval when active', () => {
    const s = M.restore(null, 'session', [12], now);
    M.account(s, 12, 60000, now, true);
    M.account(s, 12, 900000, now, false);
    M.account(s, -99, 900000, now, true);
    assert.deepEqual(s.seconds, {'12': 60});
});
test('uses elapsed duration, not wall time spent suspended', () => {
    const s = M.restore(null, 'session', [1], now);
    M.account(s, 1, 2000, now + 3600000, true);
    assert.equal(s.seconds['1'], 2);
});
test('midnight clears yesterday and accounts only today', () => {
    const s = M.restore(null, 'session', [1], now);
    s.seconds['1'] = 500;
    M.account(s, 1, 60000, new Date(2026, 8, 27, 0, 0, 10).getTime(), true);
    assert.equal(s.seconds['1'], 10);
});
test('usage follows workspace swaps without overwriting a counter', () => {
    const s = M.restore(null, 'session', [1, 2], now);
    s.seconds = {'1': 60, '2': 120};
    M.remap(s, {'1': 2, '2': 1});
    assert.deepEqual(s.seconds, {'1': 120, '2': 60});
});
test('new compositor and removed workspaces do not inherit history', () => {
    const raw = {version: 1, instance: 'old', day: M.dayKey(now), seconds: {'1': 60, '2': 120}};
    assert.deepEqual(M.restore(raw, 'new', [1], now).seconds, {});
    assert.deepEqual(M.restore(raw, 'old', [1], now).seconds, {'1': 60});
});
