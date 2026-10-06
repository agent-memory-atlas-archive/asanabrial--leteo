# Builds this checkout and installs the result on Windows, with the search model
# from the same checkout, and points the agents that already have Leteo
# configured at the new binary.
#
# Run from any PowerShell location:
#
#   <checkout>\scripts\build-install.ps1
#
# This is the developer's path. `install.ps1` fetches a published archive into
# `%LOCALAPPDATA%\leteo\bin`; this one installs into Cargo's own root, so a
# source build never lands on top of a release install.
#
# Variables, all optional:
#   CARGO_INSTALL_ROOT, CARGO_HOME  where the binary goes, as Cargo reads them
#   LETEO_SETUP_AGENTS              agents to set up, as slugs separated by
#                                   whitespace. Unset, empty or only blanks
#                                   means the agents that already have Leteo
#                                   configured, and no others. The exact word
#                                   `none`, alone, sets up no agent.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
# `rust-version` in Cargo.toml is "1.97"; the patch release is pinned here so
# two developers build with the same compiler. 1.97.0 builds this crate.
$toolchain = '1.97.0'
# The checkout, not this script's own directory: the script lives in `scripts/`
# and everything below builds the crate one level up.
$repository = Split-Path -Parent $PSScriptRoot

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "'$Name' is required but is not available on PATH. Install Rust from https://rustup.rs/ and run this script again."
    }
}

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Program $($Arguments -join ' ')' failed with exit code $LASTEXITCODE."
    }
}

Require-Command 'rustup'
Require-Command 'cargo'

# Cargo's install root, resolved once and absolutely so the directory written to
# is the directory checked afterwards. The fallback is Cargo's own default,
# `~\.cargo`. Cargo's `install.root` config key is not read: a machine that sets
# it should set `CARGO_INSTALL_ROOT` as well. A relative root is taken from the
# caller's working directory, before any `Push-Location`. `Combine` and the
# one-argument `GetFullPath`, because the two-argument form does not exist in
# Windows PowerShell 5.1.
$installRoot = if ($env:CARGO_INSTALL_ROOT) {
    $env:CARGO_INSTALL_ROOT
} elseif ($env:CARGO_HOME) {
    $env:CARGO_HOME
} elseif ($HOME) {
    Join-Path $HOME '.cargo'
} else {
    throw 'cannot tell where Cargo installs binaries: set HOME, CARGO_HOME or CARGO_INSTALL_ROOT.'
}
$installRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).ProviderPath, $installRoot))

Write-Host "Installing Rust $toolchain if needed"
Invoke-Checked 'rustup' @('toolchain', 'install', $toolchain, '--profile', 'minimal')

Push-Location $repository
try {
    Write-Host 'Compiling Leteo in release mode'
    Invoke-Checked 'rustup' @('run', $toolchain, 'cargo', 'build', '--release', '--locked')

    Write-Host 'Installing the compiled binary'
    try {
        Invoke-Checked 'rustup' @('run', $toolchain, 'cargo', 'install', '--root', $installRoot, '--path', '.', '--locked', '--force')
    } catch {
        throw "$($_.Exception.Message) If the executable was in use, close the agents running Leteo and run the script again."
    }
} finally {
    Pop-Location
}

$leteo = Join-Path (Join-Path $installRoot 'bin') 'leteo.exe'
if (-not (Test-Path -LiteralPath $leteo -PathType Leaf)) {
    throw "Cargo reported success, but the installed executable was not found at '$leteo'."
}

Write-Host 'Installing the model and configuring agents'
Invoke-Checked $leteo @('--version')

# The model in this checkout, not the one `model install` would download for the
# binary's version tag: an unreleased build has no such tag to match.
Invoke-Checked $leteo @('model', 'install', '--from', (Join-Path (Join-Path $repository 'assets') 'model'))

# Which agents get setup run again. `leteo setup` with no agent configures
# nothing off a terminal (it lists the agents) and is a wizard on one, so the
# agents are named. By default only those that already carry Leteo are named: a
# rebuild moves the binary, and what has to follow it is an existing entry, not
# a new one in an agent this developer never set up. The question is put to the
# binary rather than to the agents' files: its `was_configured` is the same
# `is_configured` check `setup` itself uses.
#
# The command is `leteo uninstall` without `--yes`, which is a preview and
# removes nothing (src/cli/mod.rs, `dry_run: !*yes`); that is what keeps this
# safe. The `dry_run` check below only refuses to read a reply that is not a
# preview as a list of agents. It runs after the command and could not undo a
# removal, so it is not the safeguard.
#
# A reply with no `agents` field is an error naming the command, and not "no
# agent configured": the second means the binary listed agents and none had
# Leteo.
#
# Plain `setup <agent>`, with no `--instructions` or `--hooks`: a typed flag is
# refused for an agent that cannot take it (OpenCode has no lifecycle hooks, Pi
# no instruction file), and one refusal would stop the loop. Plain setup writes
# the MCP entry, which is what has to follow the binary to its new location;
# instructions and hooks stay a deliberate `leteo setup <agent> --instructions
# --hooks`. It also resets that entry's `--tools` and `--project` to the
# defaults, so an entry edited by hand needs the edit again.
#
# LETEO_SETUP_AGENTS is read the same way as in build-install.sh: blanks
# collapsed, and nothing left means unset; `none` is the whole value, exactly
# (case-sensitive).
$requested = @($env:LETEO_SETUP_AGENTS -split '\s+' | Where-Object { $_ })
if ($requested.Count -gt 0) {
    $agents = $requested
} else {
    $preview = (& $leteo uninstall | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "'$leteo uninstall' failed while looking for configured agents."
    }
    try {
        $report = $preview | ConvertFrom-Json
    } catch {
        throw "'$leteo uninstall' printed a reply that is not JSON: $($_.Exception.Message)"
    }
    if ($report.dry_run -ne $true) {
        throw "'$leteo uninstall' did not report a preview; refusing to read it as a list of agents."
    }
    if (-not ($report.PSObject.Properties.Name -contains 'agents') -or @($report.agents).Count -eq 0) {
        throw "'$leteo uninstall' listed no agents, so the reply could not be read."
    }
    $agents = @($report.agents | Where-Object { $_.was_configured -eq $true } | ForEach-Object { $_.agent })
    if ($agents.Count -eq 0) {
        Write-Host "No agent has Leteo configured, so none is set up again. Run '$leteo setup <agent>' to add one."
        $agents = @('none')
    }
}
if (-not ($agents.Count -eq 1 -and $agents[0] -ceq 'none')) {
    foreach ($agent in $agents) {
        Invoke-Checked $leteo @('setup', $agent)
    }
}

Invoke-Checked $leteo @('doctor')

Write-Host "Installation finished: $leteo"
