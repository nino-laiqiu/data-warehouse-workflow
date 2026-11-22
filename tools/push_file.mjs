#!/usr/bin/env node
/**
 * 备用推送通道：当 git push 不通时，用 GitHub REST 直接写文件。
 * 场景：本机到 github.com:443 的 git 连接不稳定，但 HTTPS API 是通的。
 *
 * 用法：
 *   set GITHUB_TOKEN=ghp_xxx        # PowerShell: $env:GITHUB_TOKEN='ghp_xxx'
 *   node tools/push_file.mjs <本地路径> <仓库内路径> "<提交信息>" [分支]
 *
 * 只依赖 Node 18+ 内置 fetch。不读取凭据文件——token 一律走环境变量，
 * 避免把 .dsh/.credentials.yaml 的内容散落在工具里。
 */

const API = 'https://api.github.com';
const OWNER = process.env.GITHUB_OWNER || 'nino-laiqiu';
const REPO = process.env.GITHUB_REPO || 'data-warehouse-workflow';

const [, , localPath, remotePath, message, branch = 'main'] = process.argv;
if (!localPath || !remotePath || !message) {
  console.error('用法: node tools/push_file.mjs <本地路径> <仓库内路径> "<提交信息>" [分支]');
  process.exit(2);
}
const token = process.env.GITHUB_TOKEN;
if (!token) {
  console.error('缺少 GITHUB_TOKEN 环境变量');
  process.exit(2);
}

const fs = await import('node:fs/promises');
const content = await fs.readFile(localPath);
const base64 = content.toString('base64');

async function api(path, init = {}) {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'dw-workflow-push',
      ...(init.headers || {}),
    },
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${path}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

// 文件已存在时要带 sha，否则 422
let sha;
try {
  const existing = await api(`/repos/${OWNER}/${REPO}/contents/${encodeURI(remotePath)}?ref=${branch}`);
  sha = existing.sha;
} catch (err) {
  if (!String(err.message).startsWith('404')) throw err;
}

const body = { message, content: base64, branch };
if (sha) body.sha = sha;

const out = await api(`/repos/${OWNER}/${REPO}/contents/${encodeURI(remotePath)}`, {
  method: 'PUT',
  body: JSON.stringify(body),
});

console.log(`ok ${out.commit.sha.slice(0, 7)} ${remotePath} (${sha ? 'update' : 'create'})`);
