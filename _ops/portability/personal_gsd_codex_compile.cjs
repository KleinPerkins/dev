'use strict';
// Invoke only the exact package's text converter; never import its installer.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Module = require('node:module');
const root = fs.realpathSync(process.argv[2]);
const realLoad = Module._load;
const realResolve = Module._resolveFilename;
const builtins = new Set(['fs','path','os','crypto','util','buffer','assert','events','stream','string_decoder']);
const loaded = new Set();
const importedBuiltins = new Set();
const deniedOperationImports = new Set();
Module._load = function(request, parent, isMain) {
  const bare = request.replace(/^node:/, '');
  // The conversion dependency imports process helpers for unrelated functions.
  // Supply a throwing interface so even an accidental call cannot execute one.
  if (bare === 'child_process') {
    deniedOperationImports.add(bare);
    return new Proxy(Object.create(null), {get: (_target, key) => {
      if (key === '__esModule') return false;
      return () => { throw new Error('Forbidden child-process call: '+String(key)); };
    }});
  }
  if (Module.isBuiltin(request)) {
    if (!builtins.has(bare)) throw new Error('Forbidden package builtin: '+request);
    importedBuiltins.add(bare);
  } else {
    const resolved = realResolve.call(this, request, parent, isMain);
    if (!resolved.startsWith(root+path.sep)) throw new Error('Package import escaped reference: '+resolved);
    if (resolved === path.join(root,'bin','install.js')) throw new Error('Installer import prohibited');
    loaded.add(path.relative(root,resolved));
  }
  return realLoad.apply(this,arguments);
};
function mustDeny(operation, expected) {
  try { operation(); } catch (error) {
    if (expected(error)) return true;
    throw error;
  }
  throw new Error('Qualification guard did not deny its probe');
}
const guardProbes = {
  outside_read_denied: mustDeny(() => fs.readFileSync('/personal-gsd-denied-read-probe'), e => e.code === 'ERR_ACCESS_DENIED'),
  writes_denied: mustDeny(() => fs.writeFileSync(path.join(root,'.personal-gsd-denied-write-probe'),'x'), e => e.code === 'ERR_ACCESS_DENIED'),
  child_calls_denied: mustDeny(() => require('node:child_process').execFileSync('/usr/bin/true'), e => e.message === 'Forbidden child-process call: execFileSync'),
  network_import_denied: mustDeny(() => require('node:https'), e => e.message === 'Forbidden package builtin: node:https'),
};
const converter = require(path.join(root,'gsd-core/bin/lib/runtime-artifact-conversion.cjs'));
const skills = ['gsd-new-project','gsd-discuss-phase','gsd-plan-phase','gsd-validate-phase'];
const sha = text => crypto.createHash('sha256').update(text,'utf8').digest('hex');
const descriptors = skills.map(id => {
  const source = fs.readFileSync(path.join(root,'commands/gsd',id.slice(4)+'.md'),'utf8');
  const body = converter.convertClaudeCommandToCodexSkill(source,id);
  return {id,command_sha256:sha(source),converted_sha256:sha(body),body};
});
process.stdout.write(JSON.stringify({descriptors,loaded_modules:[...loaded].sort(),
  imported_builtins:[...importedBuiltins].sort(),denied_operation_imports:[...deniedOperationImports].sort(),HOME:process.env.HOME,
  CODEX_HOME:process.env.CODEX_HOME ?? null,installer_invoked:false,guard_probes:guardProbes,node_version:process.versions.node}));
