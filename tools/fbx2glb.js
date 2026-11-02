// FBX -> GLB без Blender: assimp, собранный в WebAssembly.
//
//   npm install assimpjs
//   node tools/fbx2glb.js model.fbx model.glb
//
// tools/retarget.py вызывает этот скрипт сам, если на вход дали .fbx
// (нужны node и пакет assimpjs рядом со скриптом или в node_modules выше).
const fs = require('fs');
const path = require('path');

function loadAssimp() {
  const tries = ['assimpjs', path.join(__dirname, 'node_modules', 'assimpjs'),
                 path.join(__dirname, '..', 'node_modules', 'assimpjs')];
  for (const t of tries) {
    try { return require(t); } catch (e) { /* next */ }
  }
  console.error('assimpjs is not installed: run "npm install assimpjs" in ' +
                path.resolve(__dirname, '..'));
  process.exit(2);
}

async function main() {
  const [inp, outp] = process.argv.slice(2);
  if (!inp || !outp) {
    console.error('usage: node tools/fbx2glb.js input.fbx output.glb');
    process.exit(2);
  }
  const assimpjs = loadAssimp();
  const ajs = await assimpjs();
  const list = new ajs.FileList();
  list.AddFile(path.basename(inp), new Uint8Array(fs.readFileSync(inp)));
  const res = ajs.ConvertFileList(list, 'glb2');
  if (!res.IsSuccess() || res.FileCount() === 0) {
    console.error('assimp could not convert ' + inp);
    process.exit(1);
  }
  fs.writeFileSync(outp, Buffer.from(res.GetFile(0).GetContent()));
  console.log('fbx2glb: ' + inp + ' -> ' + outp);
}

main();
