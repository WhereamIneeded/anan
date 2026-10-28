"""使用系统 PowerShell 验证成品下载、校验、解压及缓存回退。"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/下载并启动.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="需要 Windows 系统 PowerShell")


@pytest.fixture
def area():
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="发布入口测试-", dir=ROOT / "build") as folder:
        yield Path(folder)


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(area, body):
    command = f"""$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
try {{
    . {ps_quote(SCRIPT)}
    $area = {ps_quote(area)}
    $cache = Join-Path $area '独立缓存'
    {body}
}} catch {{
    $result = @{{ Error = $_.Exception.Message }}
}}
Write-Output ('__安安测试__' + ($result | ConvertTo-Json -Compress -Depth 10))
"""
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    environment = os.environ.copy()
    # 宿主可能运行 PowerShell 7，测试子进程只使用系统 5.1 的内置模块。
    environment["PSMODULEPATH"] = str(Path(POWERSHELL).parent / "Modules")
    try:
        process = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
    except subprocess.TimeoutExpired as error:
        trace = error.stdout or ""
        if isinstance(trace, bytes):
            trace = trace.decode("utf-8", errors="replace")
        raise AssertionError("PowerShell 行为测试超时：" + trace) from None
    assert process.returncode == 0, process.stderr
    marker = "__安安测试__"
    lines = [line for line in process.stdout.splitlines() if line.startswith(marker)]
    assert lines, process.stdout + process.stderr
    return json.loads(lines[-1][len(marker):]), process.stdout


def release(area, version="1.2.0", *, corrupt_hash=False, bad_zip=False, missing_exe=False):
    folder = area / version
    folder.mkdir()
    name = f"anan-Windows-x64-v{version}.zip"
    archive = folder / name
    if bad_zip:
        archive.write_bytes("这不是有效压缩包".encode("utf-8"))
    else:
        with zipfile.ZipFile(archive, "w") as output:
            if not missing_exe:
                output.writestr("安安/安安.exe", "测试文件，禁止执行")
            output.writestr("安安/_internal/必要运行组件.dll", "完整运行组件")
            output.writestr("安安/使用说明.txt", "测试成品说明")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums = folder / "SHA256SUMS.txt"
    sums.write_text(f"{'0' * 64 if corrupt_hash else digest}  {name}\n", encoding="utf-8")
    metadata = {
        "tag_name": f"desktop-{version}",
        "assets": [
            {"id": int(version.replace(".", "")), "name": name, "browser_download_url": f"https://example.invalid/{version}/成品"},
            {"name": "SHA256SUMS.txt", "browser_download_url": f"https://example.invalid/{version}/校验"},
        ],
    }
    (folder / "发布.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return folder


def use_release(folder):
    return f"""$script:release = Get-Content -LiteralPath {ps_quote(folder / '发布.json')} -Raw -Encoding UTF8 | ConvertFrom-Json
$script:source = {ps_quote(folder)}
$script:started = @()
function Get-AnanLatestRelease {{ return $script:release }}
function Save-AnanDownload {{
    param($Uri, $Destination)
    $name = if ($Uri.EndsWith('/校验')) {{ 'SHA256SUMS.txt' }} else {{ $script:release.assets[0].name }}
    Copy-Item -LiteralPath (Join-Path $script:source $name) -Destination $Destination
}}
function Test-AnanPackageRunning {{ param($Executable) return $false }}
function Start-AnanPackage {{ param($Executable) $script:started += $Executable }}
"""


def test_selects_only_exact_x64_product_and_checksum(area):
    folder = release(area)
    data, _ = run_ps(area, use_release(folder) + """
$script:release.assets += @(
    [pscustomobject]@{ name = 'Source code.zip'; browser_download_url = '错误源码' },
    [pscustomobject]@{ name = 'anan-Windows-arm64-v1.2.0.zip'; browser_download_url = '错误架构' },
    [pscustomobject]@{ name = '-Windows-x64-v1.0.1.zip'; browser_download_url = '旧版损坏文件名' }
)
$selected = Select-AnanReleaseAssets $script:release
$result = @{ Zip = $selected.Zip.name; Sums = $selected.Sums.name }
""")
    assert data == {"Zip": "anan-Windows-x64-v1.2.0.zip", "Sums": "SHA256SUMS.txt"}


@pytest.mark.parametrize("failure", ["不兼容附件", "重复成品", "缺少校验"])
def test_missing_or_ambiguous_assets_have_chinese_error(area, failure):
    folder = release(area)
    mutation = {
        "不兼容附件": "$script:release.assets[0].name = '-Windows-x64-v1.0.1.zip'",
        "重复成品": "$script:release.assets += $script:release.assets[0]",
        "缺少校验": "$script:release.assets = @($script:release.assets[0])",
    }[failure]
    data, _ = run_ps(area, use_release(folder) + mutation + "\nSelect-AnanReleaseAssets $script:release")
    assert "兼容成品" in data["Error"] or "校验文件" in data["Error"]


def test_hash_mismatch_is_rejected_without_activating_package(area):
    folder = release(area, corrupt_hash=True)
    data, _ = run_ps(area, use_release(folder) + """
try { Invoke-AnanReleaseLauncher -CacheRoot $cache } catch { $message = $_.Exception.Message }
$result = @{ Error = $message; Started = @($script:started).Count; Current = Test-Path (Join-Path $cache '当前.json') }
""")
    assert "SHA-256" in data["Error"]
    assert data["Started"] == 0
    assert data["Current"] is False


def test_valid_package_is_fully_extracted_and_cached_restart_does_not_download(area):
    folder = release(area)
    data, _ = run_ps(area, use_release(folder) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$package = Get-AnanCachedPackage $cache
function Save-AnanDownload { throw '缓存有效时不应重新下载成品' }
Invoke-AnanReleaseLauncher -CacheRoot $cache
$present = Test-Path -LiteralPath $package.Executable -PathType Leaf
$library = Get-Content -LiteralPath (Join-Path (Split-Path $package.Executable) '_internal/必要运行组件.dll') -Raw -Encoding UTF8
$temporaryCount = @(Get-ChildItem -LiteralPath $cache -Directory | Where-Object Name -Like '.下载-*').Count
$result = @{
    Exe = $present
    Library = "$library"
    Started = @($script:started).Count
    Temporary = $temporaryCount
}
""")
    assert data == {"Exe": True, "Library": "完整运行组件", "Started": 2, "Temporary": 0}


def test_network_failure_starts_verified_old_cache(area):
    folder = release(area)
    data, output = run_ps(area, use_release(folder) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
function Get-AnanLatestRelease { throw '网络不可用或接口请求受限' }
Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{ Started = @($script:started).Count; Preserved = (Get-AnanCachedPackage $cache).Executable -eq $old.Executable }
""")
    assert data == {"Started": 2, "Preserved": True}
    assert "已验证" in output and "缓存" in output


def test_no_release_and_no_cache_reports_chinese_error(area):
    data, _ = run_ps(area, """
function Get-AnanLatestRelease { throw '仓库尚未发布正式 Release，请等待发布或在浏览器中查看发布页。' }
Invoke-AnanReleaseLauncher -CacheRoot $cache
""")
    assert "尚未发布" in data["Error"] and "缓存" in data["Error"]


def test_running_cached_package_refuses_update_without_launch_or_download(area):
    old = release(area, "1.1.0")
    latest = release(area)
    data, output = run_ps(area, use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + """
function Test-AnanPackageRunning { param($Executable) return $true }
function Save-AnanDownload { throw '运行时不能开始更新下载' }
$exitCode = Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{ Preserved = (Get-AnanCachedPackage $cache).Executable -eq $old.Executable; Started = @($script:started).Count; ExitCode = $exitCode }
""")
    assert data == {"Preserved": True, "Started": 0, "ExitCode": 1}
    assert "先退出再更新" in output


@pytest.mark.parametrize("failure", ["下载失败", "坏压缩包", "缺少程序", "校验不符"])
def test_failed_update_preserves_and_starts_old_package(area, failure):
    old = release(area, "1.1.0")
    latest = release(area, bad_zip=failure == "坏压缩包", missing_exe=failure == "缺少程序", corrupt_hash=failure == "校验不符")
    failure_setup = "function Save-AnanDownload { throw '下载中断' }" if failure == "下载失败" else ""
    data, _ = run_ps(area, use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + failure_setup + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{
    Preserved = (Get-AnanCachedPackage $cache).Executable -eq $old.Executable
    Started = @($script:started).Count
    Temporary = @(Get-ChildItem -LiteralPath $cache -Directory | Where-Object Name -Like '.下载-*').Count
}
""")
    assert data == {"Preserved": True, "Started": 1, "Temporary": 0}


def test_tampered_cached_archive_is_not_used_offline(area):
    folder = release(area)
    data, _ = run_ps(area, use_release(folder) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$package = Get-AnanCachedPackage $cache
Set-Content -LiteralPath (Join-Path $package.Directory '成品.zip') -Value '缓存已损坏'
$script:started = @()
function Get-AnanLatestRelease { throw '网络中断' }
try { Invoke-AnanReleaseLauncher -CacheRoot $cache } catch { $message = $_.Exception.Message }
$result = @{ Error = $message; Started = @($script:started).Count }
""")
    assert "缓存" in data["Error"]
    assert data["Started"] == 0


def test_cmd_restores_system_modules_in_its_own_process(area):
    folder = release(area)
    launcher = area / "下载并启动安安.cmd"
    shutil.copy2(ROOT / "下载并启动安安.cmd", launcher)
    scripts = area / "scripts"
    scripts.mkdir()
    stub = f"""$ErrorActionPreference = 'Stop'
if (($env:PSModulePath -split ';') -contains {ps_quote(area / '宿主模块')}) {{ throw '仍在继承不兼容的宿主模块目录' }}
. {ps_quote(SCRIPT)}
$hash = Test-AnanArchiveHash -Archive {ps_quote(folder / 'anan-Windows-x64-v1.2.0.zip')} -Sums {ps_quote(folder / 'SHA256SUMS.txt')} -AssetName 'anan-Windows-x64-v1.2.0.zip'
Expand-AnanPackage -Archive {ps_quote(folder / 'anan-Windows-x64-v1.2.0.zip')} -Destination {ps_quote(area / '入口解压')}
Write-Output '系统环境验证通过'
"""
    (scripts / "下载并启动.ps1").write_text(stub, encoding="utf-8-sig")
    incompatible = area / "宿主模块"
    incompatible.mkdir()
    environment = os.environ.copy()
    environment["PSMODULEPATH"] = str(incompatible)
    process = subprocess.run(
        ["cmd.exe", "/d", "/c", str(launcher)], cwd=area, env=environment,
        input="\n", capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert "系统环境验证通过" in process.stdout


def test_cleanup_refuses_a_directory_outside_cache(area):
    outside = area / ".下载-00000000000000000000000000000000"
    outside.mkdir()
    (outside / "保留.txt").write_text("不可删除", encoding="utf-8")
    data, _ = run_ps(area, f"Remove-AnanTemporaryDirectory -Directory {ps_quote(outside)} -CacheRoot $cache")
    assert "拒绝清理" in data["Error"]
    assert (outside / "保留.txt").read_text(encoding="utf-8") == "不可删除"


def test_archive_cannot_extract_outside_temporary_directory(area):
    archive = area / "越界.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../禁止写入.txt", "越界内容")
        output.writestr("安安/安安.exe", "禁止执行")
    data, _ = run_ps(area, f"Expand-AnanPackage -Archive {ps_quote(archive)} -Destination (Join-Path $area '解压')")
    assert "拒绝解压" in data["Error"]
    assert not (area / "禁止写入.txt").exists()


def test_process_detection_uses_exact_executable_path(area):
    data, _ = run_ps(area, """
$exe = Join-Path $area '安安/安安.exe'
function Get-Process { [pscustomobject]@{ Path = 'C:\\其他应用\\安安.exe' } }
$other = Test-AnanPackageRunning $exe
function Get-Process { [pscustomobject]@{ Path = $exe } }
$same = Test-AnanPackageRunning $exe
$result = @{ Other = $other; Same = $same }
""")
    assert data == {"Other": False, "Same": True}


def test_same_filename_with_new_release_asset_is_updated(area):
    old = release(area)
    source = area / "二次发布"
    source.mkdir()
    latest = release(source)
    metadata_path = latest / "发布.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["assets"][0]["id"] = 9999
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    data, _ = run_ps(area, use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{ Updated = (Get-AnanCachedPackage $cache).Executable -ne $old.Executable; Started = @($script:started).Count }
""")
    assert data == {"Updated": True, "Started": 1}


def test_start_failure_restores_previous_cache_pointer(area):
    old = release(area, "1.1.0")
    latest = release(area)
    data, output = run_ps(area, use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + """
function Start-AnanPackage {
    param($Executable)
    if ($Executable -ne $old.Executable) { throw '新版程序启动失败' }
    $script:started += $Executable
}
Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{ Preserved = (Get-AnanCachedPackage $cache).Executable -eq $old.Executable; Started = @($script:started).Count }
""")
    assert data == {"Preserved": True, "Started": 1}
    assert "新版程序启动失败" in output


def test_new_version_replaces_cache_only_after_package_is_complete(area):
    old = release(area, "1.1.0")
    latest = release(area)
    data, _ = run_ps(area, use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$current = Get-AnanCachedPackage $cache
$result = @{ Updated = $current.Executable -ne $old.Executable; Name = $current.AssetName; Started = @($script:started).Count }
""")
    assert data == {"Updated": True, "Name": "anan-Windows-x64-v1.2.0.zip", "Started": 1}


HIDDEN_START_PROCESS = """
function Start-Process {
    param($FilePath, $WorkingDirectory, [switch]$PassThru, $ErrorAction)
    Microsoft.PowerShell.Management\\Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru:$PassThru -ErrorAction $ErrorAction
}
"""


def test_real_process_immediate_failure_is_rejected(area):
    data, _ = run_ps(area, HIDDEN_START_PROCESS + """
Start-AnanPackage (Join-Path $env:SystemRoot 'System32/where.exe')
$result = @{ Accepted = $true }
""")
    assert "Error" in data, "真实系统程序立即失败时仍被当成启动成功"
    assert "启动后立即退出" in data["Error"]


def test_real_process_immediate_failure_restores_old_cache(area):
    old = release(area, "1.1.0")
    latest = release(area)
    data, output = run_ps(area, "$script:realStarter = ${function:Start-AnanPackage}\n" + use_release(old) + """
Invoke-AnanReleaseLauncher -CacheRoot $cache
$old = Get-AnanCachedPackage $cache
""" + use_release(latest) + HIDDEN_START_PROCESS + """
function Start-AnanPackage {
    param($Executable)
    if ($Executable -ne $old.Executable) {
        & $script:realStarter (Join-Path $env:SystemRoot 'System32/where.exe')
    } else { $script:started += $Executable }
}
Invoke-AnanReleaseLauncher -CacheRoot $cache
$result = @{ Preserved = (Get-AnanCachedPackage $cache).Executable -eq $old.Executable; Started = @($script:started).Count }
""")
    assert data == {"Preserved": True, "Started": 1}
    assert "启动后立即退出" in output


@pytest.mark.parametrize("exit_code", [None, 0, 9])
def test_start_observes_process_and_only_accepts_running_package(area, exit_code):
    data, _ = run_ps(area, f"""
$script:observedMilliseconds = 0
$script:passThru = $false
$script:disposed = $false
$script:process = [pscustomobject]@{{ ExitCode = {exit_code or 0} }}
$script:process | Add-Member ScriptMethod WaitForExit {{
    param($Milliseconds)
    $script:observedMilliseconds = $Milliseconds
    return ${str(exit_code is not None).lower()}
}}
$script:process | Add-Member ScriptMethod Dispose {{ $script:disposed = $true }}
function Start-Process {{
    param($FilePath, $WorkingDirectory, [switch]$PassThru, $ErrorAction)
    $script:passThru = [bool]$PassThru
    if ($PassThru) {{ return $script:process }}
}}
try {{ Start-AnanPackage (Join-Path $area '安安.exe') }} catch {{ $message = $_.Exception.Message }}
$result = @{{ Observed = $script:observedMilliseconds; PassThru = $script:passThru; Disposed = $script:disposed; Error = "$message" }}
""")
    assert data["Observed"] == 2000
    assert data["PassThru"] is True
    assert data["Disposed"] is True
    if exit_code is None:
        assert data["Error"] == ""
    else:
        assert "启动后立即退出" in data["Error"]
