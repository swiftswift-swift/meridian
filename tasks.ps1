#Requires -Version 5.1
<#
.SYNOPSIS
    Task runner for Meridian. Run .\tasks.ps1 with no arguments to list the tasks.
.DESCRIPTION
    Every task assumes PowerShell on Windows and uses the repository-local .venv so nothing
    depends on what happens to be active in the shell.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Task = 'help',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$FrontendDir = Join-Path $RepoRoot 'frontend'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "No virtual environment found. Run: .\tasks.ps1 setup"
    }
}

function Invoke-Checked([string]$Label, [scriptblock]$Action) {
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

# Tests and the evaluation suite must never reach the network or need a key, so the offline
# providers are forced here rather than relying on whatever .env happens to contain.
function Set-OfflineEnv {
    $env:LLM_PROVIDER = 'scripted'
    $env:TOOLS_MODE = 'fixtures'
    $env:EMBEDDING_PROVIDER = 'hash'
    $env:APP_ENV = 'test'
}

function Find-Python {
    # Prefer the version SPEC names, accept the next one, and say so when falling back.
    foreach ($candidate in @('3.13', '3.14')) {
        $found = & py "-$candidate" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) {
            if ($candidate -ne '3.13') {
                Write-Warn "Python 3.13 not found; using $candidate instead."
            }
            return $found.Trim()
        }
    }
    $fallback = (Get-Command python -ErrorAction SilentlyContinue)
    if ($fallback) {
        $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ([version]$version -lt [version]'3.13') {
            throw "Python 3.13 or newer is required; found $version."
        }
        Write-Warn "Using python from PATH ($version)."
        return $fallback.Source
    }
    throw 'No suitable Python found. Install Python 3.13 or newer from python.org.'
}

function Task-Setup {
    Write-Step 'Creating the virtual environment'
    if (-not (Test-Path $VenvPython)) {
        $python = Find-Python
        Invoke-Checked 'venv creation' { & $python -m venv (Join-Path $RepoRoot '.venv') }
    }
    Write-Ok ((& $VenvPython -V) -join '')

    Write-Step 'Installing Python dependencies'
    Invoke-Checked 'pip upgrade' { & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel }
    Invoke-Checked 'pip install' { & $VenvPython -m pip install --quiet -r (Join-Path $RepoRoot 'requirements-dev.txt') }
    Write-Ok 'Python dependencies installed'

    if (Test-Path (Join-Path $FrontendDir 'package.json')) {
        Write-Step 'Installing frontend dependencies'
        Push-Location $FrontendDir
        try {
            Invoke-Checked 'npm ci' { & npm ci --no-audit --no-fund }
        } finally {
            Pop-Location
        }
        Write-Ok 'Frontend dependencies installed'
    }
    else {
        Write-Warn 'frontend/package.json not present yet; skipping npm install'
    }

    Write-Step 'Installing pre-commit hooks'
    # A hook that cannot install must not fail setup: the repository still works without it.
    & $VenvPython -m pre_commit install
    if ($LASTEXITCODE -eq 0) { Write-Ok 'pre-commit installed' } else { Write-Warn 'pre-commit hook install skipped' }

    if (-not (Test-Path (Join-Path $RepoRoot '.env'))) {
        Copy-Item (Join-Path $RepoRoot '.env.example') (Join-Path $RepoRoot '.env')
        Write-Ok 'Created .env from .env.example'
    }
    Write-Step 'Setup complete. Next: .\tasks.ps1 seed'
}

function Task-Seed {
    Assert-Venv
    Write-Step 'Seeding the demo database'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'seed' { & $VenvPython -m scripts.seed_demo @Rest }
    } finally {
        Pop-Location
    }
}

function Task-Test {
    Assert-Venv
    Set-OfflineEnv
    Write-Step 'Backend tests (offline: scripted model, fixtures, hash embeddings)'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'pytest' {
            & $VenvPython -m pytest `
                --cov=app/domain --cov=app/agent --cov=app/tools `
                --cov-report=term-missing @Rest
        }
    } finally {
        Pop-Location
    }

    if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
        Write-Step 'Frontend tests'
        Push-Location $FrontendDir
        try {
            Invoke-Checked 'vitest' { & npm run test -- --run }
        } finally {
            Pop-Location
        }
    }
    else {
        Write-Warn 'frontend/node_modules not present; skipping frontend tests'
    }
}

function Task-Lint {
    Assert-Venv
    Write-Step 'ruff format --check'
    Invoke-Checked 'ruff format' { & $VenvPython -m ruff format --check (Join-Path $RepoRoot 'app') (Join-Path $RepoRoot 'scripts') (Join-Path $RepoRoot 'tests') }
    Write-Step 'ruff check'
    Invoke-Checked 'ruff check' { & $VenvPython -m ruff check (Join-Path $RepoRoot 'app') (Join-Path $RepoRoot 'scripts') (Join-Path $RepoRoot 'tests') }
    Write-Ok 'Python lint clean'

    if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
        Write-Step 'eslint'
        Push-Location $FrontendDir
        try {
            Invoke-Checked 'eslint' { & npm run lint }
        } finally {
            Pop-Location
        }
    }
}

function Task-Typecheck {
    Assert-Venv
    Write-Step 'mypy (strict)'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'mypy' { & $VenvPython -m mypy }
    } finally {
        Pop-Location
    }
    Write-Ok 'mypy clean'

    if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
        Write-Step 'tsc --noEmit'
        Push-Location $FrontendDir
        try {
            Invoke-Checked 'tsc' { & npm run typecheck }
        } finally {
            Pop-Location
        }
    }
}

function Task-Dev {
    Assert-Venv
    Write-Step 'Starting API, worker and frontend'
    Write-Host '    API      http://localhost:8000'
    Write-Host '    Frontend http://localhost:5173  (dev server with hot reload)'
    Write-Host '    Stop everything with Ctrl+C in each window.'

    # Separate windows rather than background jobs: the worker's shutdown behaviour and the
    # reloader both need a real console to be observable, which is the point during development.
    Start-Process -FilePath 'powershell' -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$RepoRoot'; & '$VenvPython' -m uvicorn app.main:app --factory --reload --port 8000"
    )
    Start-Process -FilePath 'powershell' -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$RepoRoot'; & '$VenvPython' -m app.worker"
    )
    if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
        Start-Process -FilePath 'powershell' -ArgumentList @(
            '-NoExit', '-Command', "Set-Location '$FrontendDir'; npm run dev"
        )
    }
    Write-Ok 'Three windows started'
}

function Task-Eval {
    Assert-Venv
    Set-OfflineEnv
    Write-Step 'Running the evaluation suite'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'evaluate' { & $VenvPython -m scripts.evaluate @Rest }
    } finally {
        Pop-Location
    }
}

function Task-GenTypes {
    Assert-Venv
    Write-Step 'Generating frontend API types from the OpenAPI schema'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'export openapi' { & $VenvPython -m scripts.export_openapi }
        if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
            Push-Location $FrontendDir
            try {
                Invoke-Checked 'openapi-typescript' { & npm run gen-types }
            } finally {
                Pop-Location
            }
        }
        else {
            Write-Warn 'frontend/node_modules not present; wrote openapi.json only'
        }
    } finally {
        Pop-Location
    }
}

function Task-Build {
    Assert-Venv
    Write-Step 'Building the frontend for production'
    Push-Location $FrontendDir
    try {
        Invoke-Checked 'npm run build' { & npm run build }
    } finally {
        Pop-Location
    }
    Write-Ok 'Built to frontend/dist; FastAPI serves it at http://localhost:8000'
}

function Task-DockerUp {
    Write-Step 'docker compose up --build'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'docker compose' { & docker compose up --build @Rest }
    } finally {
        Pop-Location
    }
}

function Task-Graph {
    Assert-Venv
    Write-Step 'Exporting the LangGraph diagram'
    Push-Location $RepoRoot
    try {
        Invoke-Checked 'export graph' { & $VenvPython -m scripts.export_graph }
    } finally {
        Pop-Location
    }
}

function Task-Help {
    Write-Host ''
    Write-Host 'Meridian tasks' -ForegroundColor Cyan
    Write-Host ''
    $rows = @(
        @('setup', 'Create .venv, install Python and frontend deps, install pre-commit'),
        @('seed', 'Create and populate the demo databases (idempotent)'),
        @('dev', 'Start the API, the worker and the frontend dev server'),
        @('test', 'Run backend and frontend tests fully offline, with coverage'),
        @('lint', 'ruff format --check, ruff check, eslint'),
        @('typecheck', 'mypy --strict and tsc --noEmit'),
        @('eval', 'Run the evaluation suite and print the metrics table'),
        @('gen-types', 'Regenerate frontend API types from OpenAPI'),
        @('build', 'Build the frontend into frontend/dist'),
        @('graph', 'Export the LangGraph diagram to docs/'),
        @('docker-up', 'docker compose up --build')
    )
    foreach ($row in $rows) {
        Write-Host ('  {0,-11} {1}' -f $row[0], $row[1])
    }
    Write-Host ''
    Write-Host 'First run:' -ForegroundColor Cyan
    Write-Host '  .\tasks.ps1 setup ; .\tasks.ps1 seed ; .\tasks.ps1 dev'
    Write-Host ''
}

try {
    switch ($Task.ToLowerInvariant()) {
        'setup' { Task-Setup }
        'seed' { Task-Seed }
        'dev' { Task-Dev }
        'test' { Task-Test }
        'lint' { Task-Lint }
        'typecheck' { Task-Typecheck }
        'eval' { Task-Eval }
        'gen-types' { Task-GenTypes }
        'gentypes' { Task-GenTypes }
        'build' { Task-Build }
        'graph' { Task-Graph }
        'docker-up' { Task-DockerUp }
        'help' { Task-Help }
        default {
            Write-Host "Unknown task '$Task'." -ForegroundColor Red
            Task-Help
            exit 1
        }
    }
}
catch {
    Write-Host ''
    Write-Host "FAILED: $_" -ForegroundColor Red
    exit 1
}
