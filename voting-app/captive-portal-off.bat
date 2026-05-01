@echo off
:: Run as Administrator — removes captive portal port forwarding and firewall rules

net session >nul 2>&1 || (echo Run this as Administrator && pause && exit /b 1)

echo Removing captive portal forwarding...
netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0
netsh interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0
netsh advfirewall firewall delete rule name="FRCA Election Port 5000"
netsh advfirewall firewall delete rule name="FRCA Election Port 80"
netsh advfirewall firewall delete rule name="FRCA Election Port 443"

echo.
echo Done. All FRCA election firewall rules and port forwarding removed.
pause
