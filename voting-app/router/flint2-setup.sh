#!/bin/sh
# Configure a GL.iNet Flint 2 (OpenWrt) for the FRCA election app.
#
# Copy to the router and run over SSH:
#   scp flint2-setup.sh root@192.168.8.1:/tmp/
#   ssh root@192.168.8.1 sh /tmp/flint2-setup.sh <laptop-ethernet-mac> [--captive-portal]
#
# Sets the LAN to 10.0.0.1/24 and reserves 10.0.0.2 for the laptop.
# --captive-portal also points every hostname at the laptop (dnsmasq
# wildcard) and advertises the captive portal API (DHCP option 114).
# Running without the flag removes those two entries again.
# Safe to run more than once. WiFi name and passwords are not touched.

set -e

INITD="${INITD:-/etc/init.d}"
LAPTOP_IP="10.0.0.2"
WILDCARD="/#/${LAPTOP_IP}"
OPTION_114="114,http://${LAPTOP_IP}/api/captive-portal"

usage() {
    echo "Usage: sh flint2-setup.sh <laptop-mac xx:xx:xx:xx:xx:xx> [--captive-portal]" >&2
    exit 2
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
MAC=$(echo "$1" | tr 'A-F' 'a-f')
echo "$MAC" | grep -Eq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || usage

CAPTIVE=0
if [ $# -eq 2 ]; then
    [ "$2" = "--captive-portal" ] || usage
    CAPTIVE=1
fi

echo "LAN: 10.0.0.1/24"
uci set network.lan.ipaddr=10.0.0.1
uci set network.lan.netmask=255.255.255.0

echo "Reservation: $MAC -> $LAPTOP_IP"
uci set dhcp.frca_laptop=host
uci set dhcp.frca_laptop.name=frca-laptop
uci set dhcp.frca_laptop.mac="$MAC"
uci set dhcp.frca_laptop.ip="$LAPTOP_IP"

# Remove first so a rerun never adds a duplicate. del_list of a missing
# value is not an error worth stopping for.
uci del_list dhcp.@dnsmasq[0].address="$WILDCARD" 2>/dev/null || true
uci del_list dhcp.lan.dhcp_option="$OPTION_114" 2>/dev/null || true
if [ "$CAPTIVE" -eq 1 ]; then
    echo "Captive portal: DNS wildcard $WILDCARD and DHCP option $OPTION_114"
    uci add_list dhcp.@dnsmasq[0].address="$WILDCARD"
    uci add_list dhcp.lan.dhcp_option="$OPTION_114"
else
    echo "Captive portal: off (DNS wildcard and option 114 removed if present)"
fi

uci commit

echo
echo "Saved. Restarting the network now: this SSH session will drop."
echo "The router will then be at 10.0.0.1 (admin page: http://10.0.0.1)."
echo "Unplug and replug the laptop's ethernet cable; it should get $LAPTOP_IP."
"$INITD/network" restart
"$INITD/dnsmasq" restart
