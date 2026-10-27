#!/usr/bin/env node
/**
 * 技能正文安全扫描 + 安装。
 *
 * 技能是"别人的 prompt"，会直接影响模型行为，所以装之前先看它写了什么。
 * 命中 HARD 规则就**中止安装**并打印原文，交人判断。
 */

import { readFileSync, readdirSync, copyFileSync, mkdirSync, existsSync, cpSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const SRC = process.argv[2];
const DEST = process.argv[3];
const DRY = process.argv.includes('--dry');

if (!SRC || !DEST) {
  console.error('usage: install-skills.mjs <srcSkillsDir> <destSkillsDir> [--dry]');
  process.exitCode = 2;
  process.exit();
}

// 硬拦截：出现就停
const HARD = [
  /ignore\s+(all\s+)?(previous|prior|above)\s+instructions/i,
  /disregard\s+(the\s+)?(system|user)/i,
  /bypass\s+(the\s+)?(approval|permission|sandbox|policy)/i,
  /--dangerously-skip-permissions/i,
  /\bsudo\b/,
  /rm\s+-rf\s+\//,
  /exfiltrat/i,
  /curl[^|\n]*\|\s*(ba)?sh/,
  /base64\s+(-d|--decode)/,
  /~\/\.ssh|id_rsa|\.credentials|credentials\.yaml/i,
  /send\s+(the\s+)?(token|key|secret|content)\s+to/i,
];

// 提示级：出现只记录，不拦
const SOFT = [/\bhttp:\/\//i, /\bfetch\s*\(/i, /\beval\s*\(/i, /\bchild_process\b/];

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out);
    else if (/\.(md|mjs|js|sh|json)$/.test(e.name)) out.push(full);
  }
  return out;
}

const files = walk(SRC);
let hard = 0;
let soft = 0;
console.log(`扫描 ${files.length} 个文件…`);
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  const lines = text.split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const re of HARD) {
      if (re.test(line)) {
        hard += 1;
        console.log(`HARD  ${path.relative(SRC, file)}:${i + 1}  ${line.trim().slice(0, 120)}`);
      }
    }
    for (const re of SOFT) {
      if (re.test(line)) {
        soft += 1;
        if (soft <= 8) console.log(`soft  ${path.relative(SRC, file)}:${i + 1}  ${line.trim().slice(0, 100)}`);
      }
    }
  });
}
console.log(`\n硬命中 ${hard} 条，提示 ${soft} 条`);

if (hard > 0) {
  console.log('\n有硬命中，**中止安装**。请人工判断这些行是否可接受。');
  process.exitCode = 1;
  process.exit();
}

// 校验每个技能都有合法 frontmatter（宿主技能的硬要求）
let invalid = 0;
for (const e of readdirSync(SRC, { withFileTypes: true })) {
  if (!e.isDirectory() || e.name === '_shared') continue;
  const skillMd = path.join(SRC, e.name, 'SKILL.md');
  if (!existsSync(skillMd)) {
    console.log(`WARN  ${e.name} 没有 SKILL.md，跳过`);
    invalid += 1;
    continue;
  }
  const raw = readFileSync(skillMd, 'utf8');
  const m = /^---\r?\n([\s\S]*?)\r?\n---/u.exec(raw);
  if (!m || !/^description:\s*\S/mu.test(m[1])) {
    console.log(`WARN  ${e.name}/SKILL.md 缺少 frontmatter 或 description`);
    invalid += 1;
  }
}
if (invalid) {
  console.log(`\n${invalid} 个技能不合格，中止`);
  process.exitCode = 1;
  process.exit();
}

if (DRY) {
  console.log('\n--dry：不写盘');
  process.exitCode = 0;
  process.exit();
}

// 安装：平铺复制（保留 ../_shared 的相对引用）
mkdirSync(DEST, { recursive: true });
let copied = 0;
for (const e of readdirSync(SRC, { withFileTypes: true })) {
  if (!e.isDirectory()) continue;
  const from = path.join(SRC, e.name);
  const to = path.join(DEST, e.name);
  cpSync(from, to, { recursive: true });
  copied += 1;
}
console.log(`\n已复制 ${copied} 个目录 -> ${DEST}`);
