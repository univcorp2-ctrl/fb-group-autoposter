# Put saved Messenger drafts into the already logged-in regular Chrome work profile.
# NEVER sends a message: no Enter in the composer and no Send-button click.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$RepoRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$DraftsPath=Join-Path $RepoRoot 'messenger\data\drafts.json'
$StatusPath=Join-Path $RepoRoot 'messenger\data\work_profile_draft_status.json'
$Chrome='C:\Program Files\Google\Chrome\Application\chrome.exe'
$ProfileDirectory='Profile 1'
if(!(Test-Path $DraftsPath)){throw 'drafts.json not found'}
$payload=Get-Content -LiteralPath $DraftsPath -Raw -Encoding UTF8|ConvertFrom-Json
$rows=@($payload.drafts|Where-Object{$_.url -and $_.draft}|Select-Object -First 5)
$ws=New-Object -ComObject WScript.Shell
$results=@()
foreach($row in $rows){
 Start-Process -FilePath $Chrome -ArgumentList @("--profile-directory=$ProfileDirectory",[string]$row.url)|Out-Null
 Start-Sleep -Seconds 4
 $activated=$false
 for($i=0;$i -lt 12;$i++){if($ws.AppActivate('Messenger')){$activated=$true;break};Start-Sleep -Milliseconds 500}
 if(!$activated){$results+=[pscustomobject]@{thread_id=$row.thread_id;name=$row.name;placed=$false;reason='messenger_window_not_activated'};continue}
 $b64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$row.draft))
 $js="(()=>{let a=[...document.querySelectorAll('div[contenteditable=\"true\"][role=\"textbox\"],div[contenteditable=\"true\"],textarea')].filter(e=>e.offsetParent!==null);let e=a[a.length-1];let t=new TextDecoder().decode(Uint8Array.from(atob('$b64'),c=>c.charCodeAt(0)));if(!e){document.title='DRAFT_FAIL_NO_COMPOSER';return;}e.focus();if(e.isContentEditable){document.execCommand('selectAll',false,null);document.execCommand('insertText',false,t);}else{let s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;s.call(e,t);e.dispatchEvent(new Event('input',{bubbles:true}));}document.title='DRAFT_OK_'+t.length;})()"
 [Windows.Forms.Clipboard]::SetText($js)
 $ws.SendKeys('^l');Start-Sleep -Milliseconds 200;$ws.SendKeys('javascript:');Start-Sleep -Milliseconds 100;$ws.SendKeys('^v');Start-Sleep -Milliseconds 150;$ws.SendKeys('{ENTER}');Start-Sleep -Seconds 2
 $results+=[pscustomobject]@{thread_id=$row.thread_id;name=$row.name;placed=$true;reason='injected_no_send'}
}
[pscustomobject]@{checked_at=(Get-Date).ToString('s');profile_directory=$ProfileDirectory;count=$results.Count;results=$results}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $StatusPath -Encoding UTF8
