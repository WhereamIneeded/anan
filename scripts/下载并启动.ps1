# 函数可点加载；只有直接运行脚本时才联网并启动程序。

function Get-AnanLatestRelease {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        return Invoke-RestMethod -Uri 'https://api.github.com/repos/WhereamIneeded/anan/releases/latest' `
            -Headers @{ Accept = 'application/vnd.github+json'; 'User-Agent' = 'Anan-Desktop-Launcher' } `
            -TimeoutSec 30 -ErrorAction Stop
    } catch {
        $status = 0
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -eq 404) {
            throw '仓库尚未发布正式 Release，请等待发布或在浏览器中查看发布页。'
        }
        if ($status -eq 403 -or $status -eq 429) {
            throw 'GitHub 接口暂时限制请求，请稍后重试或在浏览器中下载成品。'
        }
        throw "无法查询最新发布，请检查网络后重试：$($_.Exception.Message)"
    }
}

function Select-AnanReleaseAssets {
    param($Release)
    $zip = @($Release.assets | Where-Object {
        $_.name -cmatch '^anan-Windows-x64-v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?\.zip$'
    })
    if ($zip.Count -ne 1) {
        throw '当前 Release 不包含唯一的兼容成品（Windows x64），请等待新版或在浏览器中查看发布页。'
    }
    $sums = @($Release.assets | Where-Object { $_.name -ceq 'SHA256SUMS.txt' })
    if ($sums.Count -ne 1) { throw '当前 Release 缺少唯一的 SHA256SUMS.txt 校验文件，请等待新版。' }
    return [pscustomobject]@{ Zip = $zip[0]; Sums = $sums[0] }
}

function Save-AnanDownload {
    param([string]$Uri, [string]$Destination)
    Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing -TimeoutSec 180 -ErrorAction Stop
}

function Test-AnanArchiveHash {
    param([string]$Archive, [string]$Sums, [string]$AssetName)
    $hashes = @(foreach ($line in Get-Content -LiteralPath $Sums -Encoding UTF8 -ErrorAction Stop) {
        if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$' -and $Matches[2] -ceq $AssetName) {
            $Matches[1].ToLowerInvariant()
        }
    })
    if ($hashes.Count -ne 1) { throw 'SHA-256 校验文件中没有该成品的唯一记录。' }
    $actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256 -ErrorAction Stop).Hash
    if ($actual -ne $hashes[0]) { throw 'SHA-256 校验失败，已拒绝使用本次下载的成品。' }
    return $hashes[0]
}

function Expand-AnanPackage {
    param([string]$Archive, [string]$Destination)
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $prefix = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
        $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
        try {
            foreach ($entry in $zip.Entries) {
                $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
                if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw '压缩包包含超出解压目录的文件，已拒绝解压。'
                }
            }
        } finally { $zip.Dispose() }
        Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -ErrorAction Stop
    } catch { throw "成品解压失败：$($_.Exception.Message)" }
    $executable = Join-Path $Destination '安安\安安.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw '成品解压后缺少 安安\安安.exe，请等待完整成品发布。'
    }
    return $executable
}

function Get-AnanCachedPackage {
    param([string]$CacheRoot)
    try {
        $current = Get-Content -LiteralPath (Join-Path $CacheRoot '当前.json') -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        if ($current.Directory -cnotmatch '^版本-[0-9a-f]{32}$') { return $null }
        $directory = Join-Path $CacheRoot $current.Directory
        $record = Get-Content -LiteralPath (Join-Path $directory '已校验.json') -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json
        if ($record.Sha256 -notmatch '^[0-9a-f]{64}$') { return $null }
        $executable = Join-Path $directory '程序\安安\安安.exe'
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { return $null }
        $actual = (Get-FileHash -LiteralPath (Join-Path $directory '成品.zip') -Algorithm SHA256 -ErrorAction Stop).Hash
        if ($actual -ne $record.Sha256) { return $null }
        return [pscustomobject]@{
            Directory = $directory; Executable = $executable; AssetName = $record.AssetName; AssetId = $record.AssetId
        }
    } catch { return $null }
}

function Test-AnanPackageRunning {
    param([string]$Executable)
    foreach ($process in Get-Process -Name '安安' -ErrorAction SilentlyContinue) {
        if ([string]::Equals($process.Path, $Executable, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Start-AnanPackage {
    param([string]$Executable)
    $process = Start-Process -FilePath $Executable -WorkingDirectory (Split-Path -Parent $Executable) -PassThru -ErrorAction Stop
    try {
        if ($process.WaitForExit(2000)) {
            throw "安安启动后立即退出（退出码：$($process.ExitCode)），请检查成品运行环境或重新下载。"
        }
    } finally { $process.Dispose() }
}

function Remove-AnanTemporaryDirectory {
    param([string]$Directory, [string]$CacheRoot)
    $rootPath = [IO.Path]::GetFullPath($CacheRoot).TrimEnd('\') + '\'
    $fullPath = [IO.Path]::GetFullPath($Directory)
    if (-not $fullPath.StartsWith($rootPath, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $fullPath) -cnotmatch '^\.下载-[0-9a-f]{32}$') {
        throw '拒绝清理缓存目录之外的路径。'
    }
    if (Test-Path -LiteralPath $fullPath) { Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop }
}

function Set-AnanCurrentPackage {
    param([string]$CacheRoot, [string]$Directory)
    $pending = Join-Path $CacheRoot ('.当前-' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        @{ Directory = $Directory } | ConvertTo-Json | Set-Content -LiteralPath $pending -Encoding UTF8 -ErrorAction Stop
        $current = Join-Path $CacheRoot '当前.json'
        if (Test-Path -LiteralPath $current) { [IO.File]::Replace($pending, $current, [NullString]::Value) }
        else { [IO.File]::Move($pending, $current) }
    } finally {
        if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction Stop }
    }
}

function Invoke-AnanReleaseLauncher {
    param([string]$CacheRoot = (Join-Path $env:LOCALAPPDATA '安安桌宠\成品缓存'))
    $ErrorActionPreference = 'Stop'
    New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
    $cached = Get-AnanCachedPackage $CacheRoot
    $temporary = $null
    $published = $false
    $updating = $false
    try {
        Write-Host '正在前台检查安安最新成品……'
        $assets = Select-AnanReleaseAssets (Get-AnanLatestRelease)
        if ($cached -and $cached.AssetName -ceq $assets.Zip.name -and $cached.AssetId -and $cached.AssetId -eq $assets.Zip.id) {
            if (Test-AnanPackageRunning $cached.Executable) { Write-Host '安安已经在运行。'; return 0 }
            Start-AnanPackage $cached.Executable
            return 0
        }
        $updating = $true
        if ($cached -and (Test-AnanPackageRunning $cached.Executable)) {
            Write-Host '安安正在运行，请先退出再更新。现有成品保持不变。'
            return 1
        }
        $identifier = [guid]::NewGuid().ToString('N')
        $temporary = Join-Path $CacheRoot ('.下载-' + $identifier)
        New-Item -ItemType Directory -Path $temporary | Out-Null
        $archive = Join-Path $temporary '成品.zip'
        $sums = Join-Path $temporary 'SHA256SUMS.txt'
        Write-Host ('正在下载并校验：' + $assets.Zip.name)
        Save-AnanDownload -Uri $assets.Sums.browser_download_url -Destination $sums
        Save-AnanDownload -Uri $assets.Zip.browser_download_url -Destination $archive
        $hash = Test-AnanArchiveHash -Archive $archive -Sums $sums -AssetName $assets.Zip.name
        $null = Expand-AnanPackage -Archive $archive -Destination (Join-Path $temporary '程序')
        @{ AssetName = $assets.Zip.name; AssetId = $assets.Zip.id; Sha256 = $hash } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $temporary '已校验.json') -Encoding UTF8
        if ($cached -and (Test-AnanPackageRunning $cached.Executable)) { throw '安安正在运行，请先退出再更新。' }
        # 新包完整可用后才原子切换入口，旧包保留，失败不会替换旧成品。
        $folder = '版本-' + $identifier
        $destination = Join-Path $CacheRoot $folder
        Move-Item -LiteralPath $temporary -Destination $destination
        Set-AnanCurrentPackage -CacheRoot $CacheRoot -Directory $folder
        $published = $true
        Start-AnanPackage (Join-Path $destination '程序\安安\安安.exe')
        Write-Host '安安已启动。'
        return 0
    } catch {
        if ($published) {
            if ($cached) { Set-AnanCurrentPackage -CacheRoot $CacheRoot -Directory (Split-Path -Leaf $cached.Directory) }
            else { Remove-Item -LiteralPath (Join-Path $CacheRoot '当前.json') -Force }
        }
        if (-not $cached) { throw "无法下载并启动安安：$($_.Exception.Message) 本机没有已验证的可用缓存。" }
        Write-Host ("未能获取或启动最新成品：$($_.Exception.Message)")
        Write-Host '继续使用本机已验证的旧版缓存。'
        if (Test-AnanPackageRunning $cached.Executable) {
            if ($updating) { Write-Host '安安正在运行，请先退出再更新。'; return 1 }
            Write-Host '安安已在运行，继续使用本机已验证的缓存。'
            return 0
        }
        Start-AnanPackage $cached.Executable
        return 0
    } finally {
        if ($temporary) { Remove-AnanTemporaryDirectory -Directory $temporary -CacheRoot $CacheRoot }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (-not [Environment]::Is64BitOperatingSystem) { throw '安安成品需要 Windows x64 系统。' }
        $exitCode = Invoke-AnanReleaseLauncher
        exit $exitCode
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        Write-Host '发布页：https://github.com/WhereamIneeded/anan/releases/latest'
        exit 1
    }
}
