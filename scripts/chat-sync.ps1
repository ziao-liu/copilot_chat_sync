[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$PythonExecutable = "",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ToolArguments
)

$ErrorActionPreference = "Stop"
$candidates = @()
if ($PythonExecutable) {
    $candidates += [PSCustomObject]@{ Exe = $PythonExecutable; Prefix = @() }
} else {
    if ($env:CONDA_PREFIX) {
        $candidates += [PSCustomObject]@{ Exe = (Join-Path $env:CONDA_PREFIX "python.exe"); Prefix = @() }
    }
    foreach ($name in @("python", "py", "python3")) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($command) {
            $prefix = @()
            if ($name -eq "py") { $prefix = @("-3") }
            $candidates += [PSCustomObject]@{ Exe = $command.Source; Prefix = $prefix }
        }
    }
    foreach ($folder in @("miniconda3", "anaconda3")) {
        $candidates += [PSCustomObject]@{ Exe = (Join-Path $env:USERPROFILE "$folder\python.exe"); Prefix = @() }
    }
}

$python = $null
$probe = "import sys; assert sys.version_info >= (3, 10); print('CCS_PYTHON=' + sys.executable)"
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate.Exe -PathType Leaf)) { continue }
    if ($candidate.Exe -match "\\WindowsApps\\python[0-9.]*\.exe$") { continue }
    try {
        $prefix = $candidate.Prefix
        $output = & $candidate.Exe @prefix -c $probe 2>&1
        $status = $LASTEXITCODE
        $marker = @($output | Where-Object { "$_" -match "^CCS_PYTHON=" })
        if ($status -eq 0 -and $marker.Count -eq 1) {
            $python = "$($marker[0])".Substring(11)
            break
        }
    } catch {
        continue
    }
}

if (-not $python) {
    [Console]::Error.WriteLine("No working Python 3.10+ found. Use an activated conda prompt, or pass -PythonExecutable with its full path. Windows Store placeholders are not Python.")
    exit 2
}

$previousPath = $env:PYTHONPATH
$exitCode = 2
try {
    $source = (Resolve-Path (Join-Path $PSScriptRoot "..\src")).Path
    $env:PYTHONPATH = $source
    if ($previousPath) { $env:PYTHONPATH += ";$previousPath" }
    & $python -m copilot_chat_sync @ToolArguments
    $exitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPath
}
exit $exitCode
