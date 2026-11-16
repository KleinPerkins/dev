'use strict';
// Disposable qualification of exact upstream public emitters; no install/main call.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Module = require('node:module');
const net = require('node:net');
const root = fs.realpathSync(process.argv[2]);
const stage = fs.realpathSync(process.argv[3]);
if (fs.readdirSync(stage).length !== 0) throw new Error('Stage must be empty');
if (process.env.GSD_TEST_MODE !== '1') throw new Error('Explicit module test mode required');
const home = process.env.HOME;
const codexHome = process.env.CODEX_HOME;
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
if (sha(fs.readFileSync(path.join(root,'bin/install.js'))) !== '04d48e7013c0653c065fa4f8e1599862adcdd6d6b528466c5f568a692044ae59') throw new Error('Installer module bytes changed');
const loaded = new Set();
const builtins = new Set(['fs','path','os','crypto','util','buffer','assert','events','stream','string_decoder','readline','tty','url','vm']);
const realLoad = Module._load;
const realResolve = Module._resolveFilename;
const builtinImports = new Set();
const childImports = new Set();
const logs = {log:0,info:0,warn:0,error:0,debug:0};
for (const name of Object.keys(logs)) console[name] = () => { logs[name]++; };
Module._load = function(request,parent,isMain) {
  const bare = request.replace(/^node:/,'');
  if (bare === 'child_process') {
    childImports.add(bare);
    return new Proxy(Object.create(null),{get:(_target,key) => {
      if (key === '__esModule') return false;
      return () => { throw new Error('Child-process operation prohibited'); };
    }});
  }
  if (Module.isBuiltin(request)) {
    if (!builtins.has(bare)) throw new Error('Package builtin prohibited: '+bare);
    builtinImports.add(bare);
  } else {
    const resolved = realResolve.call(this,request,parent,isMain);
    if (!resolved.startsWith(root+path.sep)) throw new Error('Package import escaped verified root');
    loaded.add(path.relative(root,resolved));
  }
  return realLoad.apply(this,arguments);
};
function denied(operation) {
  try { operation(); } catch (error) {
    if (error.code === 'ERR_ACCESS_DENIED') return true;
    throw error;
  }
  throw new Error('Filesystem probe was not denied');
}
async function networkDenied() {
  return await new Promise((resolve,reject) => {
    const socket = new net.Socket();
    socket.setTimeout(1000,()=>{socket.destroy();reject(new Error('Network denial probe timed out'));});
    socket.once('connect',()=>{socket.destroy();reject(new Error('Network denial probe connected'));});
    socket.once('error',error=>{
      socket.destroy();
      if (error.code === 'EPERM' || error.code === 'EACCES') resolve(true);
      else reject(new Error('OS network denial not established: '+error.code));
    });
    socket.connect(9,'127.0.0.1');
  });
}
async function main() {
  const guards = {
    source_write_denied: denied(()=>fs.writeFileSync(path.join(root,'.prohibited-write'),'x')),
    outside_read_denied: denied(()=>fs.readFileSync('/personal-gsd-prohibited-read')),
    outside_write_denied: denied(()=>fs.writeFileSync('/personal-gsd-prohibited-write','x')),
    network_os_denied: await networkDenied(),
  };
  try { require('node:child_process').execFileSync('/usr/bin/true'); }
  catch(error) { if (error.message !== 'Child-process operation prohibited') throw error; guards.child_call_denied=true; }
  if (!guards.child_call_denied) throw new Error('Child probe was not denied');
  // require.main differs and GSD_TEST_MODE is true: only module initialization runs.
  const upstream = require(path.join(root,'bin/install.js'));
  if (typeof upstream.copyWithPathReplacement !== 'function' || typeof upstream.installCodexConfig !== 'function') throw new Error('Missing public emitter');
  // Keep the whole pinned package layout. Runtime modules have package-owned
  // sibling-script dependencies; the gsd-core/ subtree alone is not a closure.
  function copyPackage(dir,dest) {
    for (const entry of fs.readdirSync(dir,{withFileTypes:true})) {
      const source=path.join(dir,entry.name),target=path.join(dest,entry.name);
      if (entry.isDirectory()) {
        fs.mkdirSync(target,{mode:0o700});copyPackage(source,target);
      } else if (entry.isFile()) {
        fs.copyFileSync(source,target);fs.chmodSync(target,0o600);
      } else throw new Error('Special package companion path refused');
    }
  }
  copyPackage(root,stage);
  upstream.copyWithPathReplacement(path.join(root,'gsd-core'),path.join(stage,'gsd-core'),
    '$HOME/.codex/','codex',false,true,stage);
  const conversion = require(path.join(root,'gsd-core/bin/lib/runtime-artifact-conversion.cjs'));
  const skills = ['gsd-new-project','gsd-discuss-phase','gsd-plan-phase','gsd-validate-phase'];
  const selectedStaging=path.join(stage,'.personal-codex-selected-staging');
  fs.mkdirSync(selectedStaging,{mode:0o700});
  for (const id of skills) {
    const dest = path.join(selectedStaging,id);fs.mkdirSync(dest,{recursive:true});
    const content = fs.readFileSync(path.join(root,'commands/gsd',id.slice(4)+'.md'),'utf8');
    fs.writeFileSync(path.join(dest,'SKILL.md'),conversion.convertClaudeCommandToCodexSkill(content,id));
  }
  conversion.rewriteStagedSkillBodies(selectedStaging,{
    runtime:'codex',configDir:path.join(home,'.codex'),scope:'global',resolveAttribution:()=>undefined,
  });
  for (const id of skills) {
    fs.copyFileSync(path.join(selectedStaging,id,'SKILL.md'),path.join(stage,'skills',id,'SKILL.md'));
  }
  fs.rmSync(selectedStaging,{recursive:true});
  // The upstream whole-role emitter otherwise probes real home defaults and
  // ancestor project configurations. Qualify it through its public fs-injection
  // seam with explicit fixture inputs; never reinterpret a denied host read.
  const fsSeam = require(path.join(root,'gsd-core/bin/lib/install-fs-adapter.cjs'));
  const actualAdapter = fsSeam.installFs();
  const globalDefaultsPath = path.join(home,'.gsd','defaults.json');
  const virtualDefaults = '{}\n';
  const fixtureConfig = {runtime:'codex',model_profile:'inherit'};
  fs.mkdirSync(path.join(stage,'.planning'));
  fs.writeFileSync(path.join(stage,'.planning','config.json'),JSON.stringify(fixtureConfig)+'\n');
  let virtualDefaultReads=0;
  function boundPath(value) {
    if (typeof value !== 'string') throw new Error('Non-string fixture fs path refused');
    const resolved=path.resolve(value);
    if (resolved !== stage && !resolved.startsWith(stage+path.sep) &&
        resolved !== root && !resolved.startsWith(root+path.sep)) {
      throw new Error('Unbound fixture filesystem path refused');
    }
    return value;
  }
  const fixtureAdapter={...actualAdapter,
    existsSync(value) {
      if (value === globalDefaultsPath) return true;
      return actualAdapter.existsSync(boundPath(value));
    },
    readFileSync(value,encoding) {
      if (value === globalDefaultsPath) {
        virtualDefaultReads++;
        return encoding ? virtualDefaults : Buffer.from(virtualDefaults);
      }
      return actualAdapter.readFileSync(boundPath(value),encoding);
    },
  };
  const roleCount = fsSeam.withInstallFs(fixtureAdapter,()=>
    upstream.installCodexConfig(stage,path.join(root,'agents'),'codex-agent-sandbox'));
  if (process.env.HOME !== home || process.env.CODEX_HOME !== codexHome) throw new Error('Home environment changed');
  const files=[];
  function walk(dir) {
    for (const entry of fs.readdirSync(dir,{withFileTypes:true})) {
      const full=path.join(dir,entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) files.push({path:path.relative(stage,full),sha256:sha(fs.readFileSync(full)),bytes:fs.statSync(full).size});
      else throw new Error('Special emitted path refused');
    }
  }
  walk(stage);files.sort((a,b)=>a.path.localeCompare(b.path));
  const modules=[...loaded].sort().map(name=>({path:name,sha256:sha(fs.readFileSync(path.join(root,name)))}));
  process.stdout.write(JSON.stringify({schema:'personal-portability/gsd-codex-bundle-emission/v1',
    node_version:process.versions.node,guards,files,modules,builtin_imports:[...builtinImports].sort(),denied_child_imports:[...childImports].sort(),
    package_module_initialized:true,package_install_main_invoked:false,
    complete_package_companions_preserved:true,
    public_emitters:['copyWithPathReplacement','installCodexConfig'],role_count:roleCount,
    native_skill_ids:skills,HOME_preserved:true,CODEX_HOME_preserved:true,
    native_roots_changed:false,model_worker_launched:false,log_call_counts:logs,
    configuration_fixture:{upstream_public_fs_seam:true,project:fixtureConfig,
      global_defaults_sha256:sha(Buffer.from(virtualDefaults)),
      virtual_global_default_reads:virtualDefaultReads,real_home_configuration_read:false}}));
}
main().catch(error=>{process.stderr.write(String(error.stack || error));process.exitCode=1;});
