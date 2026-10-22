const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../extension/background.js'), 'utf8');
const start = source.indexOf('async function postingWindowId()');
const end = source.indexOf('async function dispatchOneTask()', start);
assert(start >= 0 && end > start, 'background task must establish a same-profile window');
const code = source.slice(start, end);
async function check(windows, expected, shouldCreate) {
  const calls = [];
  const chrome = { windows: {
    getAll: async () => windows,
    create: async options => { calls.push(options); return { id: 99 }; },
  }};
  const getWindow = vm.runInNewContext(`(${code})`, { chrome });
  assert.equal(await getWindow(), expected);
  assert.equal(calls.length, shouldCreate ? 1 : 0);
  if (shouldCreate) {
    assert.equal(calls[0].focused, false);
    assert.equal(calls[0].state, 'minimized');
    assert.equal(calls[0].url, 'about:blank');
  }
}
(async () => {
  await check([], 99, true);
  await check([{ id: 7, type: 'normal', incognito: false }], 7, false);
  await check([{ id: 8, type: 'normal', incognito: true }], 99, true);
  assert(source.includes('windowId: await postingWindowId()'));
  console.log('PASS: background owner window, existing window reuse, and no incognito fallback');
})().catch(error => { console.error(error); process.exit(1); });
