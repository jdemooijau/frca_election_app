@echo off
:: Run as Administrator — enables captive portal port forwarding and firewall rules
:: Only needed when using the GL.iNet Flint 2 router for the election/demo

net session >nul 2>&1 || (echo Run this as Administrator && pause && exit /b 1)

echo Setting up captive portal forwarding...
netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=5000 connectaddress=127.0.0.1
netsh interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=5000 connectaddress=127.0.0.1
netsh advfirewall firewall add rule name="FRCA Election Port 5000" dir=in action=allow protocol=TCP localport=5000
netsh advfirewall firewall add rule name="FRCA Election Port 80" dir=in action=allow protocol=TCP localport=80
netsh advfirewall firewall add rule name="FRCA Election Port 443" dir=in action=allow protocol=TCP localport=443

echo.
echo Done. Ports 80, 443 forwarding to 5000. Firewall rules added.
echo Run captive-portal-off.bat to clean up when finished.
pause
