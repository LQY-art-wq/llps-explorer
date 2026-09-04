$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$commonPaths = @(
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
    (Join-Path $env:ProgramData 'DockerDesktop\version-bin\docker.exe')
)
$dockerService = Get-Service -Name 'com.docker.service' -ErrorAction SilentlyContinue
$dockerProcesses = @(Get-Process -Name 'Docker Desktop', 'com.docker.backend' -ErrorAction SilentlyContinue)
$alternatives = @('podman', 'nerdctl', 'lima', 'minikube', 'kind', 'multipass')

$result = [ordered]@{
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    host_platform = 'windows'
    docker_cli_available = $null -ne $dockerCommand
    docker_common_installation_found = @($commonPaths | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0
    docker_service_found = $null -ne $dockerService
    docker_process_found = $dockerProcesses.Count -gt 0
    alternative_container_cli_found = @($alternatives | Where-Object { $null -ne (Get-Command $_ -ErrorAction SilentlyContinue) }).Count -gt 0
    linux_containers_confirmed = $false
    docker_daemon_confirmed = $false
    docker_compose_confirmed = $false
    status = 'DOCKER_RUNTIME_UNAVAILABLE'
}

$result | ConvertTo-Json -Depth 3
