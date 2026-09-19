param([string]$Destination = 'D:\Relico')
$ErrorActionPreference = 'Stop'
function Plain([Security.SecureString]$value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
try {
    Write-Host "RELYQO: ежедневные копии / Kundalik nusxalar"
    Write-Host "Компьютер должен быть включён, вход в Windows выполнен. / Kompyuter yoqilgan bo‘lishi kerak."
    Write-Host "Сохраните пароль копии отдельно. / Nusxa parolini alohida saqlang."
    $destination = [IO.Path]::GetFullPath($Destination)
    Write-Host ("Папка копий / Nusxalar papkasi: " + $destination)
    if ($destination -notmatch '^[A-Za-z]:\\' -or !(Test-Path -LiteralPath ([IO.Path]::GetPathRoot($destination)) -PathType Container)) {
        Write-Host "Диск для папки копий недоступен. Подключите диск и повторите настройку. / Nusxalar diski mavjud emas. Diskni ulang va qayta urinib ko‘ring." -ForegroundColor Red
        exit 1
    }
    try { $null = [IO.Directory]::CreateDirectory($destination) }
    catch {
        Write-Host "Не удалось создать папку копий. Проверьте доступ к диску. / Nusxalar papkasini yaratib bo‘lmadi. Diskka kirishni tekshiring." -ForegroundColor Red
        exit 1
    }
    $server = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server.json') -Raw | ConvertFrom-Json
    $uri = [uri]$server.base_url
    if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') { throw 'Invalid server URL.' }
    Write-Host ("Сайт / Sayt: " + $uri.GetLeftPart([UriPartial]::Authority))
    $token = Read-Host "Вставьте ключ из админки / Paneldagi kalitni kiriting" -AsSecureString
    if ((Plain $token) -notmatch '^rqbackup_[A-Za-z0-9_-]{40,100}$') { throw 'Invalid export key.' }
    $phrase = Read-Host "Пароль копий, 16–200 символов / Nusxa paroli, 16–200 belgi" -AsSecureString
    $confirmation = Read-Host "Повторите пароль / Parolni takrorlang" -AsSecureString
    if ((Plain $phrase).Length -lt 16 -or (Plain $phrase).Length -gt 200 -or (Plain $phrase) -cne (Plain $confirmation)) { throw 'Passphrases do not match or are too short.' }
    $root = Join-Path $env:LOCALAPPDATA 'RELYQO\Backup'
    $null = New-Item -ItemType Directory -Path $root -Force
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $identity = New-Object Security.Principal.SecurityIdentifier($sid)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $root -AclObject $acl
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Backup.ps1') -Destination (Join-Path $root 'Backup.ps1') -Force
    $configuration = [pscustomobject]@{ BaseUrl=$uri.GetLeftPart([UriPartial]::Authority); Token=$token; Passphrase=$phrase; Destination=$destination }
    $configuration | Export-Clixml -LiteralPath (Join-Path $root 'settings.xml')
    Write-Host "Создаём первую копию. Подождите несколько минут. / Birinchi nusxa yaratilmoqda."
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File (Join-Path $root 'Backup.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'First backup failed. Schedule was not enabled.' }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "' + (Join-Path $root 'Backup.ps1') + '"')
    $daily = New-ScheduledTaskTrigger -Daily -At '19:00'
    $login = New-ScheduledTaskTrigger -AtLogOn -User $sid
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
    $null = Register-ScheduledTask -TaskName 'RELYQO Daily Backup' -Action $action -Trigger @($daily,$login) -Settings $settings -Principal $principal -Force
    Write-Host ("Готово: каждый день в 19:00 и при входе. Файлы / Fayllar: " + $destination)
    Write-Host "Старые копии сохраняются. Храните вторую копию на другом устройстве. / Eski nusxalar saqlanadi."
} catch {
    Write-Host "Настройка не завершена. Проверьте ключ, пароль, интернет и Планировщик Windows. / Sozlash tugamadi." -ForegroundColor Red
    exit 1
} finally { $configuration=$null; $token=$null; $phrase=$null; $confirmation=$null }
