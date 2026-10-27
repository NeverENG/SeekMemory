#!/usr/bin/env node
/**
 * 最小 tar.gz 解包器：不依赖系统 tar，不受 PATH 限制。
 * 只处理 npm 包这种常规情形（ustar 头、文件与目录、无长名扩展）。
 *
 * 用法：node tools/untar.mjs <file.tgz> <outDir>
 */

import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import path from 'node:path';

const [tgz, outDir] = process.argv.slice(2);
if (!tgz || !outDir) {
  console.error('usage: untar.mjs <file.tgz> <outDir>');
  process.exitCode = 2;
  process.exit();
}

const buf = gunzipSync(readFileSync(tgz));
const root = path.resolve(outDir);
mkdirSync(root, { recursive: true });

let off = 0;
let count = 0;
const cstr = (b, start, len) => {
  const slice = b.subarray(start, start + len);
  const end = slice.indexOf(0);
  return slice.subarray(0, end === -1 ? slice.length : end).toString('utf8');
};

while (off + 512 <= buf.length) {
  const name = cstr(buf, off, 100);
  if (!name) break; // 结束块
  const size = parseInt(cstr(buf, off + 124, 12).trim() || '0', 8);
  const type = cstr(buf, off + 156, 1) || '0';
  const prefix = cstr(buf, off + 345, 155);
  const full = prefix ? `${prefix}/${name}` : name;
  const dataStart = off + 512;

  if (type === '0' || type === '') {
    const target = path.join(root, full);
    if (!path.resolve(target).startsWith(root)) throw new Error(`unsafe path: ${full}`);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, buf.subarray(dataStart, dataStart + size));
    count += 1;
  }
  off = dataStart + Math.ceil(size / 512) * 512;
}

console.log(`extracted ${count} files -> ${root}`);
