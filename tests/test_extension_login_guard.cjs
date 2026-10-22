const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname,'../extension/content.js'),'utf8');
const body = source.slice(source.indexOf('  function loginLooksBroken()'),source.indexOf('  function normalizeText',source.indexOf('  function loginLooksBroken()')));
function broken(href, input=null) {
  const sandbox={location:{href},URL,document:{querySelector:()=>input}};
  vm.createContext(sandbox); vm.runInContext(body+'; result=loginLooksBroken()',sandbox);
  return sandbox.result;
}
assert.equal(broken('https://www.facebook.com/groups/123#fbautoposter_task=recovery-layout-a'),false);
assert.equal(broken('https://www.facebook.com/login/?next=groups/123'),true);
assert.equal(broken('https://www.facebook.com/checkpoint/123'),true);
assert.equal(broken('https://www.facebook.com/recover/initiate'),true);
assert.equal(broken('https://www.facebook.com/groups/123',{}),true);
console.log('login-path and recovery-task regression checks passed');
