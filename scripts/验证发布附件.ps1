$ErrorActionPreference = 'Stop'
$env:PSModulePath = Join-Path $PSHOME 'Modules'
$tag = "desktop-$env:GITHUB_RUN_NUMBER-$env:GITHUB_RUN_ATTEMPT"
$script:publishedRelease = gh api "repos/$env:GITHUB_REPOSITORY/releases/tags/$tag" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
. (Join-Path $PSScriptRoot '下载并启动.ps1')
# 使用本次发布的真实元数据，避免其他并发发布改变 latest。
function Get-AnanLatestRelease { return $script:publishedRelease }
function Start-AnanPackage {
    param([string]$Executable)
    $process = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -WorkingDirectory (Split-Path -Parent $Executable) -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        throw '发布成品启动检查超时，已结束本次测试进程。'
    }
    if ($process.ExitCode -ne 0) { throw "发布成品启动失败：$($process.ExitCode)" }
}
$cache = Join-Path $env:RUNNER_TEMP '安安发布验收'
Invoke-AnanReleaseLauncher -CacheRoot $cache
$package = Get-AnanCachedPackage $cache
if (-not $package) { throw '发布附件未形成有效缓存。' }
$version = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $package.Executable) '版本.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($version.'源码提交' -ne $env:GITHUB_SHA -or $version.'构建时有未提交修改' -ne $false) {
    throw '发布附件的源码提交或干净构建标记不一致。'
}
Write-Host "发布附件下载、校验、解压和启动通过：$tag"
