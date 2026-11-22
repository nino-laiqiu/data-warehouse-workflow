#!/usr/bin/env node
/**
 * 批量把本地文件推送到 GitHub（走 Git Data API，一次提交）。
 *
 * 为什么需要它：本机 git 到 github.com:443 经常超时（`Failed to connect ... 443`），
 * 而 api.github.com 稳定。它和 tools/push_file.mjs 的分工是：
 *   push_file.mjs  改 1 个文件（Contents API，带 sha 覆盖）
 *   push_batch.mjs 改 N 个文件（Git Data API，一次 commit，原子）
 *
 * 用法：
 *   GITHUB_TOKEN=xxx node tools/push_batch.mjs "提交信息" README.md knowledge/wiki/README.md
 * 环境变量：
 *   GITHUB_TOKEN   必填，classic PAT（repo scope）
 *   GITHUB_REPO    默认 nino-laiqiu/data-warehouse-workflow
 *   GITHUB_BRANCH  默认 main
 */
import { readFile } from 'node:fs/promises';

const REPO = process.env.GITHUB_REPO || 'nino-laiqiu/data-warehouse-workflow';
const BRANCH = process.env.GITHUB_BRANCH || 'main';
const TOKEN = process.env.GITHUB_TOKEN;
const [message, ...files] = process.argv.slice(2);

const API = `https://api.github.com/repos/${REPO}`;

if (!TOKEN) fail('缺少 GITHUB_TOKEN');
if (!message || files.length === 0) fail('用法: node tools/push_batch.mjs "提交信息" <文件...>');

function fail(msg) {
  console.error(`ERROR: ${msg}`);
  process.exit(1);
}

async function api(method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'dsh-push-batch',
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) fail(`${method} ${path} -> ${res.status}\n${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : null;
}

const ref = await api('GET', `/git/ref/heads/${BRANCH}`);
const parentSha = ref.object.sha;
const parent = await api('GET', `/git/commits/${parentSha}`);
console.log(`基提交 ${parentSha.slice(0, 7)} (${parent.message.split('\n')[0]})`);

const tree = [];
for (const path of files) {
  let content;
  try {
    content = await readFile(path);
  } catch {
    fail(`读不到文件 ${path}`);
  }
  const blob = await api('POST', '/git/blobs', {
    content: content.toString('base64'),
    encoding: 'base64',
  });
  tree.push({ path: path.replaceAll('\\', '/'), mode: '100644', type: 'blob', sha: blob.sha });
  console.log(`  blob ${path} ${content.length}B`);
}

const newTree = await api('POST', '/git/trees', { base_tree: parent.tree.sha, tree });
const commit = await api('POST', '/git/commits', {
  message,
  tree: newTree.sha,
  parents: [parentSha],
});
await api('PATCH', `/git/refs/heads/${BRANCH}`, { sha: commit.sha, force: false });

console.log(`OK ${BRANCH} -> ${commit.sha.slice(0, 7)}（${files.length} 个文件）`);
console.log(`https://github.com/${REPO}/commit/${commit.sha}`);
