$ErrorActionPreference='Stop'
$project = Split-Path $PSScriptRoot
foreach ($name in @('Setup.ps1','Backup.ps1')) {
    $tokens=$null; $errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $project ('app\backup-client\'+$name)),[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ('PowerShell parse errors in '+$name+': '+($errors | ForEach-Object { $_.Message + " at line " + $_.Extent.StartLineNumber } | Out-String)) }
}
$testRoot=Join-Path $env:TEMP ('relyqo-backup-test-'+[guid]::NewGuid().ToString('N'))
$null=New-Item -ItemType Directory -Path $testRoot
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$identity = New-Object Security.Principal.SecurityIdentifier($ownerSid)
$rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $testRoot -AclObject $acl
if (!(Get-Acl -LiteralPath $testRoot).AreAccessRulesProtected) { throw 'Private settings directory inherited broad permissions.' }
$fixtureToken='rqbackup_test_token_not_a_real_credential_1234567890'
$fixturePhrase='fixture-backup-passphrase-12345'
$config=[pscustomobject]@{BaseUrl='https://example.test';Token=(ConvertTo-SecureString $fixtureToken -AsPlainText -Force);Passphrase=(ConvertTo-SecureString $fixturePhrase -AsPlainText -Force);Destination=$testRoot}
$configPath=Join-Path $testRoot 'settings.xml'
$config | Export-Clixml -LiteralPath $configPath
$xml=Get-Content -LiteralPath $configPath -Raw
if ($xml.Contains($fixtureToken) -or $xml.Contains($fixturePhrase)) { throw 'Secret appeared unencrypted in Windows settings.' }
$script:fixtureBytes=[Text.Encoding]::ASCII.GetBytes("RELYQO-BACKUP-1`nfixture-encrypted-payload")
$script:receiptCount=0
function Invoke-WebRequest {
    param($Uri,$Method,$Headers,$ContentType,$Body,$TimeoutSec,$MaximumRedirection,[switch]$UseBasicParsing)
    if ($Uri -ne 'https://example.test/v1/backup-client/export' -or $Headers.Authorization -ne ('Bearer '+$fixtureToken)) { throw 'Incorrect export scope or credential.' }
    $request=[Text.Encoding]::UTF8.GetString($Body)|ConvertFrom-Json
    if ($request.passphrase -ne $fixturePhrase) { throw 'DPAPI roundtrip failed.' }
    $algorithm=[Security.Cryptography.SHA256]::Create()
    try { $digest=([BitConverter]::ToString($algorithm.ComputeHash($script:fixtureBytes))).Replace('-','').ToLowerInvariant() } finally { $algorithm.Dispose() }
    return [pscustomobject]@{Headers=@{'X-Backup-SHA256'=$digest};RawContentStream=(New-Object IO.MemoryStream(,$script:fixtureBytes))}
}
function Invoke-RestMethod {
    param($Uri,$Method,$Headers,$ContentType,$Body,$TimeoutSec,$MaximumRedirection)
    if ($Uri -ne 'https://example.test/v1/backup-client/receipt') { throw 'Wrong receipt endpoint.' }
    $files=@(Get-ChildItem -LiteralPath $testRoot -Filter '*.rqbackup')
    if ($files.Count -ne 1) { throw 'Receipt sent before atomic file save.' }
    $digest=(Get-FileHash -LiteralPath $files[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if (($Body|ConvertFrom-Json).sha256 -ne $digest) { throw 'Receipt digest mismatch.' }
    $script:receiptCount++
    return @{ok=$true}
}
# Only this disposable fixture exposes the underlying exception; no real secrets are used.
$backupCode=Get-Content -LiteralPath (Join-Path $project 'app\backup-client\Backup.ps1') -Raw
$backupCode=$backupCode.Replace('    # Never write exception objects', "    throw`n    # Never write exception objects")
& ([scriptblock]::Create($backupCode)) -ConfigPath $configPath
if ($script:receiptCount -ne 1 -or !(Get-Content (Join-Path $testRoot 'last-status.txt') -Raw).Contains(' OK ')) { throw 'Success was not recorded.' }
# Exercise the actual Windows Task Scheduler API using a harmless task in this disposable runner.
$taskName='RELYQO-Test-'+[guid]::NewGuid().ToString('N')
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
try {
    $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -Command exit 0'
    $triggers=@((New-ScheduledTaskTrigger -Daily -At '19:00'),(New-ScheduledTaskTrigger -AtLogOn -User $sid))
    $principal=New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    $null=Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal
    if ((Get-ScheduledTask -TaskName $taskName).Triggers.Count -ne 2) { throw 'Both triggers were not registered.' }
} finally {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
Write-Host 'Windows DPAPI, download, atomic save, receipt, and scheduled task checks passed.'
