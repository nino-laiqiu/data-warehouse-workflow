<#
.SYNOPSIS
  把本地改动提交到 GitHub（API 通道，替代 git push）。

.DESCRIPTION
  一条命令完成：读凭据 → 收集改动 → 调 tools/push_batch.mjs → 打印提交链接。
  为什么不在窗口里手敲这一串：每次都要重来一遍"token 在哪、node 在哪、
  中文提交信息怎么传"，忘一步就卡住。这里把易忘的部分固化下来。

.EXAMPLE
  pwsh tools/push.ps1 -Message "feat: 新增画像标签质量规则" -All

.EXAMPLE
  pwsh tools/push.ps1 -Message "fix: 改 README" -Files README.md,docs/推送流程.md

.EXAMPLE
  # 删除远端文件：路径前加减号
  pwsh tools/push.ps1 -Message "chore: 删除废弃文件" -Files "-old/file.md"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Message,
  [string[]]$Files,
  [switch]$All,
  [string]$Repo = 'nino-laiqiu/data-warehouse-workflow',
  [string]$Branch = 'main',
  [string]$TokenFile = 'C:\Users\nino\.dsh\.credentials.yaml',
  [string]$Node = 'F:\node\node.exe'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$tmp = Join-Path $root '.tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

# 1) token
if (-not (Test-Path -LiteralPath $TokenFile)) { throw "凭据文件不存在: $TokenFile" }
$line = Get-Content -LiteralPath $TokenFile -Encoding UTF8 |
  Where-Object { $_ -match '^\s*GITHUB_MCP_PAT\s*:' } | Select-Object -First 1
if (-not $line) { throw "凭据文件里没有 GITHUB_MCP_PAT 条目" }
$token = ($line -replace '^\s*GITHUB_MCP_PAT\s*:\s*', '').Trim().Trim('"').Trim("'")
if ($token -notmatch '^(ghp_|github_pat_)' -or $token.Length -lt 30) {
  throw "GITHUB_MCP_PAT 看起来不是有效 token（长度 $($token.Length)）"
}

# 2) 文件清单
$entries = New-Object System.Collections.Generic.List[string]
if ($Files) {
  foreach ($f in $Files) { $entries.Add($f) }
}
elseif ($All) {
  $statusFile = Join-Path $tmp 'status.txt'
  $statusErr = Join-Path $tmp 'status.err'
  # 注意：Start-Process -PassThru 的 ExitCode 在这里可能为空值，不能拿来判成败，
  # 只能看 stderr 是否真的写了东西。
  Start-Process -FilePath 'git' -ArgumentList @('-c', 'core.quotepath=false', 'status', '--porcelain') `
    -NoNewWindow -Wait -RedirectStandardOutput $statusFile -RedirectStandardError $statusErr | Out-Null
  $errText = if (Test-Path -LiteralPath $statusErr) { (Get-Content -LiteralPath $statusErr -Raw -Encoding UTF8) } else { '' }
  if ($errText -and $errText.Trim()) { throw "git status 失败: $errText" }

  foreach ($l in (Get-Content -LiteralPath $statusFile -Encoding UTF8)) {
    if ($l.Trim().Length -lt 4) { continue }
    $xy = $l.Substring(0, 2)
    $path = $l.Substring(3).Trim()
    if ($path.StartsWith('"') -and $path.EndsWith('"')) { $path = $path.Trim('"') }
    if ($path -match ' -> ') { $path = ($path -split ' -> ')[-1] }   # 重命名取新名

    if ($path -like '.tmp/*' -or $path -like '*/__pycache__/*' -or $path -like '__pycache__/*') { continue }

    if (Test-Path -LiteralPath $path -PathType Container) {
      $inner = Get-ChildItem -LiteralPath $path -Recurse -File -Force |
        ForEach-Object { $_.FullName.Substring($root.Length + 1).Replace('\', '/') } |
        Where-Object { $_ -notlike '*__pycache__*' }
      foreach ($i in $inner) { $entries.Add($i) }
      continue
    }
    if ($xy -match 'D') { $entries.Add("-$path") } else { $entries.Add($path) }
  }
}
else {
  throw "要么给 -Files，要么给 -All（自动收集改动）"
}

$entries = @($entries | Where-Object { $_ } | Select-Object -Unique)
if ($entries.Count -eq 0) { Write-Host '没有需要推送的改动'; exit 0 }

# 3) 落到文件再传参（PowerShell 会按空格重切参数，中文/换行必须走文件）
$msgPath = Join-Path $tmp 'push-msg.txt'
$filesPath = Join-Path $tmp 'push-files.txt'
[IO.File]::WriteAllText($msgPath, $Message, (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllLines($filesPath, $entries, (New-Object Text.UTF8Encoding($false)))

Write-Host "推送 $($entries.Count) 个文件 → $Repo ($Branch)"
Get-Content -LiteralPath $filesPath -Encoding UTF8 | ForEach-Object { "  $_" }

# 4) 调 node
$env:GITHUB_TOKEN = $token
$env:GITHUB_REPO = $Repo
$env:GITHUB_BRANCH = $Branch
$outFile = Join-Path $tmp 'push-out.txt'
$errFile = Join-Path $tmp 'push-err.txt'
Start-Process -FilePath $Node -ArgumentList @('tools/push_batch.mjs', '--msg-file', $msgPath, '--files-from', $filesPath) `
  -NoNewWindow -Wait -RedirectStandardOutput $outFile -RedirectStandardError $errFile | Out-Null

$outText = if (Test-Path -LiteralPath $outFile) { (Get-Content -LiteralPath $outFile -Raw -Encoding UTF8) } else { '' }
$errText = if (Test-Path -LiteralPath $errFile) { (Get-Content -LiteralPath $errFile -Raw -Encoding UTF8) } else { '' }
if ($outText -and $outText.Trim()) { Write-Host $outText.TrimEnd() }
if ($errText -and $errText.Trim()) { Write-Host $errText.TrimEnd() }

# 判成败同样不看 ExitCode：成功时脚本会打印 "OK <branch> -> <sha>"
if ($outText -notmatch 'OK\s+\S+\s*->') {
  throw '推送失败：node 没有输出 OK（看上面的错误信息）'
}

Write-Host ''
Write-Host '下一步：本地与远端对齐（API 提交的 sha 和本地不同，属正常）'
Write-Host '  git -c credential.helper= -c http.sslBackend=openssl fetch origin main'
Write-Host '  git reset --hard origin/main   # 只在 fetch 成功之后执行！'
