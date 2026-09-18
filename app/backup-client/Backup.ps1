param([string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'RELYQO\Backup\settings.xml'))
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Plain([Security.SecureString]$value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
$pendingFile = $null
try {
    $config = Import-Clixml -LiteralPath $ConfigPath
    $server = [uri]$config.BaseUrl
    if ($server.Scheme -ne 'https' -or $server.UserInfo -or $server.Query -or $server.Fragment -or $server.AbsolutePath -ne '/') { throw 'Invalid HTTPS server address.' }
    $baseUrl = $server.GetLeftPart([UriPartial]::Authority)
    $headers = @{ Authorization = 'Bearer ' + (Plain $config.Token) }
    $body = @{ passphrase = (Plain $config.Passphrase) } | ConvertTo-Json -Compress
    $name = 'relyqo-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.rqbackup'
    $finalFile = Join-Path $config.Destination $name
    $pendingFile = $finalFile + '.partial'
    $reply = Invoke-WebRequest -Uri ($baseUrl + '/v1/backup-client/export') -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -UseBasicParsing -TimeoutSec 240 -MaximumRedirection 0
    $fileStream = [IO.File]::Open($pendingFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $reply.RawContentStream.Position = 0; $reply.RawContentStream.CopyTo($fileStream); $fileStream.Flush($true) }
    finally { $fileStream.Dispose(); $reply.RawContentStream.Dispose() }
    $digest = (Get-FileHash -LiteralPath $pendingFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($digest -ne [string]$reply.Headers['X-Backup-SHA256']) { throw 'Downloaded checksum does not match.' }
    $magic = [Text.Encoding]::ASCII.GetBytes("RELYQO-BACKUP-1`n")
    $stream = [IO.File]::OpenRead($pendingFile)
    try { $prefix = New-Object byte[] $magic.Length; $count = $stream.Read($prefix, 0, $magic.Length) }
    finally { $stream.Dispose() }
    if ($count -ne $magic.Length) { throw 'Invalid backup format.' }
    for ($i=0; $i -lt $magic.Length; $i++) { if ($prefix[$i] -ne $magic[$i]) { throw 'Invalid backup format.' } }
    Move-Item -LiteralPath $pendingFile -Destination $finalFile
    $pendingFile = $null
    try {
        $null = Invoke-RestMethod -Uri ($baseUrl + '/v1/backup-client/receipt') -Method Post -Headers $headers -ContentType 'application/json' -Body (@{sha256=$digest} | ConvertTo-Json -Compress) -TimeoutSec 60 -MaximumRedirection 0
    } catch { throw 'Backup saved, but the server did not receive confirmation. Check the destination folder.' }
    [IO.File]::WriteAllText((Join-Path (Split-Path $ConfigPath) 'last-status.txt'), ([DateTime]::UtcNow.ToString('o') + ' OK ' + $name))
    Write-Host "Зашифрованная копия сохранена. / Shifrlangan nusxa saqlandi."
} catch {
    # Never write exception objects, request bodies, tokens or passphrases into logs.
    if ($pendingFile -and (Test-Path -LiteralPath $pendingFile)) { Remove-Item -LiteralPath $pendingFile }
    [IO.File]::WriteAllText((Join-Path (Split-Path $ConfigPath) 'last-status.txt'), ([DateTime]::UtcNow.ToString('o') + ' FAILED. Check internet, key validity and free disk space.'))
    Write-Error "Копирование не завершено. Проверьте папку копий и состояние в админке. / Nusxalash tugamadi."
    exit 1
} finally { $body = $null; $headers = $null; $config = $null }
