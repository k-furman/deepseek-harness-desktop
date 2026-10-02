param([Parameter(Mandatory = $true)][string]$Path)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Read the actual MSI database rather than inferring architecture from its name.
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.GetType().InvokeMember('OpenDatabase', 'InvokeMethod', $null, $installer, @((Resolve-Path $Path).Path, 0))
$view = $database.GetType().InvokeMember('OpenView', 'InvokeMethod', $null, $database, @("SELECT Value FROM Property WHERE Property = 'ProductVersion'"))
$null = $view.GetType().InvokeMember('Execute', 'InvokeMethod', $null, $view, $null)
$record = $view.GetType().InvokeMember('Fetch', 'InvokeMethod', $null, $view, $null)
$version = $record.GetType().InvokeMember('StringData', 'GetProperty', $null, $record, @(1))
$summary = $database.GetType().InvokeMember('SummaryInformation', 'GetProperty', $null, $database, @(0))
$template = $summary.GetType().InvokeMember('Property', 'GetProperty', $null, $summary, @(7))
@{ version = $version; template = $template } | ConvertTo-Json -Compress
