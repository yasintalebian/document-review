# Run on Windows with Microsoft Word installed. Reads the source without saving it.
param([Parameter(Mandatory=$true)][string]$DocumentPath,
      [Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$source = (Resolve-Path -LiteralPath $DocumentPath).Path
function Hash-Text([string]$value) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Clean-Text([string]$value) { return $value.Replace([string][char]13,'').Replace([string][char]7,'').Replace([string][char]9,'').Trim() }
$zip = [IO.Compression.ZipFile]::OpenRead($source)
try {
    $reader = [IO.StreamReader]::new($zip.GetEntry('word/document.xml').Open())
    try { [xml]$xml = $reader.ReadToEnd() } finally { $reader.Dispose() }
} finally { $zip.Dispose() }
$ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
$ns.AddNamespace('w','http://schemas.openxmlformats.org/wordprocessingml/2006/main')
$paragraphs = $xml.SelectNodes('/w:document/w:body//w:p[not(ancestor::w:txbxContent)]',$ns)
$sourceCounts = @{}
$texts = @()
foreach ($p in $paragraphs) {
    $text = ($p.SelectNodes('./w:r/w:t',$ns) | ForEach-Object { $_.InnerText }) -join ''
    $texts += $text
    $key = Hash-Text (Clean-Text $text)
    if (-not $sourceCounts.ContainsKey($key)) { $sourceCounts[$key] = 0 }
    $sourceCounts[$key]++
}
$word = $null; $doc = $null; $map = @{}; $wordMatches = @{}
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3 # disable macros in opened documents
    $doc = $word.Documents.Open($source, $false, $true, $false)
    $doc.Repaginate()
    foreach ($p in $doc.Paragraphs) {
        $text = Clean-Text $p.Range.Text
        $key = Hash-Text $text
        $range = $p.Range.Duplicate
        $range.Collapse(1) # paragraph start, not end
        $page = [int]$range.Information(3) # page number shown in Word
        if (-not $wordMatches.ContainsKey($key)) { $wordMatches[$key] = @() }
        $wordMatches[$key] += $page
    }
    for ($i = 0; $i -lt $texts.Count; $i++) {
        $key = Hash-Text (Clean-Text $texts[$i])
        # Repeated/ambiguous paragraphs are intentionally left unmapped.
        if ($sourceCounts[$key] -eq 1 -and $wordMatches.ContainsKey($key) -and $wordMatches[$key].Count -eq 1) {
            $map[[string]$i] = @{ text_sha256 = (Hash-Text $texts[$i]); page = $wordMatches[$key][0] }
        }
    }
} finally {
    if ($doc) { $doc.Close(0) | Out-Null }
    if ($word) { $word.Quit() | Out-Null }
}
$result = @{ source_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant(); paragraphs = $map }
[IO.File]::WriteAllText($OutputPath, ($result | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
Write-Output "Mapped $($map.Count) unambiguous source paragraphs. Source DOCX was not changed."
