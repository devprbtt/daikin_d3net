$ErrorActionPreference='Continue'
Write-Output 'start'
$port='COM3'
$bauds=9600,19200,38400,57600,115200,1048576
$parities='None','Even','Odd'
$stopbits='One','Two'
function HexStr($bytes){($bytes | ForEach-Object { $_.ToString('X2') }) -join ' '}
$results=@()
foreach($b in $bauds){
  foreach($p in $parities){
    foreach($s in $stopbits){
      Write-Output "testing $b $p$s"
      $sp=$null
      $collected = New-Object System.Collections.Generic.List[byte]
      try{
        $sp = New-Object System.IO.Ports.SerialPort($port,$b,[System.IO.Ports.Parity]::$p,8,[System.IO.Ports.StopBits]::$s)
        $sp.ReadTimeout=200
        $sp.Open()
        Start-Sleep -Milliseconds 50
        $buffer = New-Object byte[] 512
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $total=0
        while($sw.ElapsedMilliseconds -lt 600){
          $n = $sp.BytesToRead
          if($n -gt 0){
            $n = $sp.Read($buffer,0,[Math]::Min($n,512))
            if($n -gt 0){
              for($i=0; $i -lt $n; $i++){
                $collected.Add($buffer[$i])
              }
              $total += $n
            }
          } else {
            Start-Sleep -Milliseconds 10
          }
        }
        $first = $collected | Select-Object -First 32
        $results += [PSCustomObject]@{Baud=$b;Parity=$p;Stop=$s;Count=$total;Sample=HexStr $first}
      } catch {
        $results += [PSCustomObject]@{Baud=$b;Parity=$p;Stop=$s;Count=-1;Sample=$_.Exception.Message}
      } finally {
        if($sp -and $sp.IsOpen){ $sp.Close() }
      }
    }
  }
}
$results | Format-Table -AutoSize
