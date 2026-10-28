"""验证发布步骤在英文 Windows 的系统 PowerShell 中能够正确解析。"""

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.skipif(not POWERSHELL, reason="需要 Windows 系统 PowerShell")
def test_release_validation_survives_runner_script_encoding():
    workflow = (ROOT / ".github/workflows/构建Windows.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: 验证发布附件下载与启动\n", 1)[1]
    shell = re.search(r"^        shell: (.+)$", step, re.M).group(1)
    body = "\n".join(line[10:] for line in step.split("        run: |\n", 1)[1].splitlines())
    # Actions 生成 UTF-8 无 BOM 临时脚本；系统 5.1 按英文 Windows 的 1252 解码。
    sources = [(body.encode("utf-8"), "windows-1252" if shell == "powershell" else "utf-8")]
    for reference in re.findall(r"\./scripts/[^\s\"']+\.ps1", body):
        data = (ROOT / reference).read_bytes()
        sources.append((data[3:], "utf-8") if data.startswith(b"\xef\xbb\xbf") else (data, "windows-1252"))
    for data, encoding in sources:
        payload = base64.b64encode(data).decode("ascii")
        command = f"""[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$source = [Text.Encoding]::GetEncoding('{encoding}').GetString([Convert]::FromBase64String('{payload}'))
$parseErrors = $null
$tokens = $null
[Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors) | Out-Null
ConvertTo-Json -InputObject @($parseErrors | ForEach-Object {{ $_.Message }}) -Compress
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        environment = os.environ.copy()
        environment["PSMODULEPATH"] = str(Path(POWERSHELL).parent / "Modules")
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", env=environment, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [], "发布校验脚本在 GitHub 英文 Windows 下解析失败：" + result.stdout
