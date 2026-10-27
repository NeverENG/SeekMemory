#!/usr/bin/env node
/**
 * 解析 app.asar 头部目录表，找出 dsh CLI 的入口文件。
 * 只读，不写任何东西。
 *
 * 用法：node tools/list-asar.mjs <path-to-app.asar>
 *   例：node tools/list-asar.mjs "C:/Users/me/AppData/Local/Programs/DeepSeek Harness/resources/app.asar"
 *
 *
 * asar 格式：
 *   0..3   uint32 = 4
 *   4..7   uint32 = pickle 头长度
 *   8..11  uint32 = 4
 *   12..15 uint32 = JSON 头长度
 *   16..   JSON（文件目录树）
 */

import { openSync, readSync, closeSync, fstatSync } from 'node:fs';

const file = process.argv[2];
if (!file) {
  console.error('usage: node tools/list-asar.mjs <path-to-app.asar>');
  console.error('hint : <DSH install dir>/resources/app.asar');
  process.exit(1);
}
const fd = openSync(file, 'r');
const size = fstatSync(fd).size;

const head = Buffer.alloc(16);
readSync(fd, head, 0, 16, 0);
const jsonSize = head.readUInt32LE(12);
const jsonBuf = Buffer.alloc(jsonSize);
readSync(fd, jsonBuf, 0, jsonSize, 16);
closeSync(fd);

const tree = JSON.parse(jsonBuf.toString('utf8'));
console.log(`asar ${(size / 1024 / 1024).toFixed(1)} MB, header ${(jsonSize / 1024).toFixed(0)} KB`);

// 顶层
console.log('\n=== 顶层条目 ===');
for (const [name, node] of Object.entries(tree.files ?? {})) {
  console.log(`  ${name}${node.files ? '/' : ''}`);
}

// dsh 下第一层 + 任何叫 cli* 的文件
const hits = [];
function walk(node, prefix) {
  for (const [name, child] of Object.entries(node.files ?? {})) {
    const p = prefix ? `${prefix}/${name}` : name;
    if (child.files) {
      if (prefix === 'dsh' || p === 'dsh') {
        for (const k of Object.keys(child.files)) hits.push(`${p}/${k}`);
      }
      walk(child, p);
    } else if (/cli|bin|index\.(js|mjs)$/i.test(name) && /^dsh\//.test(p) && p.split('/').length <= 3) {
      hits.push(p);
    }
  }
}
walk(tree, '');

console.log('\n=== dsh/ 第一层 与 cli 候选 ===');
for (const h of hits) console.log('  ' + h);
