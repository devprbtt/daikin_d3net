$port="COM3"
$sp = New-Object System.IO.Ports.SerialPort($port,19200,[System.IO.Ports.Parity]::Even,8,[System.IO.Ports.StopBits]::One)
$sp.ReadTimeout=500
$sp.Open()
Start-Sleep -Milliseconds 100
$buffer = New-Object byte[] 4096
$sw=[System.Diagnostics.Stopwatch]::StartNew()
$mem = New-Object System.Collections.Generic.List[byte]
while($sw.ElapsedMilliseconds -lt 1000){
  $n=$sp.BytesToRead
  if($n -gt 0){
    $n=$sp.Read($buffer,0,[Math]::Min($n, $buffer.Length))
    for($i=0;$i -lt $n;$i++){ $mem.Add($buffer[$i]) }
  } else { Start-Sleep -Milliseconds 5 }
}
$sp.Close()
$bytes=$mem.ToArray()
Write-Output "captured $($bytes.Length) bytes"
$hex = ($bytes | Select-Object -First 256 | ForEach-Object { $_.ToString('X2') }) -join ' '
Set-Content -Path capture_19200E1.txt -Value $hex
Write-Output "first bytes saved to capture_19200E1.txt"
