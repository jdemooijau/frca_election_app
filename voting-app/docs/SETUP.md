# Hardware and Network Setup

> **Before following these instructions, please read the disclaimer in the main README. You are fully responsible for the correct setup and operation of this software.**

This document explains how to set up the laptop and WiFi router for the election, and how to test at home beforehand.

## What You Need

| Item | Notes |
|------|-------|
| Laptop | Windows 10/11 with Python 3.11+ installed |
| Portable WiFi router | e.g. TP-Link Archer AX55 or similar. No internet connection needed. |
| Ethernet cable | Cat5e or Cat6, 1-2 metres |
| Power board | For laptop and router |
| Extension lead | Depending on hall layout |
| Projector + HDMI cable | For displaying live results (optional) |

## Setting Up the Network

The voting app needs a predictable network environment so that QR codes can be printed in advance with a known URL. Follow these steps carefully.

### Step 1: Set up the router

1. Plug in the router and power it on.
2. Connect your laptop to the router via ethernet cable.
3. Open a browser and go to `http://tplinkwifi.net` or `http://192.168.8.1`.
4. Log in using the default admin password (on the label on the bottom of the router).
5. Set a new admin password and remember it.
6. Go through the setup wizard:
   - Skip the internet connection step (or select "Don't connect to the internet")
   - Set the WiFi network name (e.g. `ChurchVote`)
   - Set a simple WiFi password (e.g. `vote2026`)
   - Save and let the router reboot

### Step 2: Configure the DHCP reservation

This ensures the laptop always gets the same IP address, so the QR codes printed in advance will work on election day.

1. Log back into the router admin page.
2. Navigate to **Advanced > Network > DHCP Server > Address Reservation**.
3. Click **Add**.
4. Select your laptop from the list of connected devices.
5. Set the reserved IP address to `192.168.8.100`.
6. Save.

From now on, whenever your laptop connects to this router, it will always receive the IP address `192.168.8.100`.

### Step 3: Verify the reservation

1. Disconnect the laptop from the router.
2. Wait 10 seconds, then reconnect.
3. Check your IP address:
   - **Windows:** Open Command Prompt and type `ipconfig`
   - **Mac:** Open Terminal and type `ifconfig | grep inet`
   - **Linux:** Open Terminal and type `ip addr`
4. Confirm your IP is `192.168.8.100`.

### Step 4: Configure the app

1. Start the app: `python app.py`
2. Log in to the admin panel and go to Setup.
3. Set the **WiFi Network Name** to match your router (e.g. `ChurchVote`).
4. Set the **WiFi Password** (e.g. `vote2026`).
5. Set the **Voting Base URL** to `http://192.168.8.100:5000`.
6. Save.

### Step 5: Verify from a phone

1. On your phone, connect to the WiFi network (e.g. `ChurchVote`).
2. Open a browser and go to `http://192.168.8.100:5000`.
3. You should see the voting code entry page.
4. If the phone shows "no internet" — that's expected. The router has no internet connection. The voting app still works.

### Step 6: Generate and print code slips

Now that the network is verified, generate the voting codes in the admin panel. The code slip PDF will include QR codes encoding the full URL (e.g. `http://192.168.8.100:5000/v/KR4T7N`), the WiFi name and password, and the fallback URL.

Brothers scan the QR code with their phone camera — the browser opens automatically with the code pre-filled.

## Projector Setup

1. Connect the projector to the laptop via HDMI.
2. Open `http://localhost:5000/display` in full-screen (F11).
3. The display auto-refreshes every second.

## Testing at Home

### Phone Hotspot

1. Turn on the phone's hotspot, connect the laptop.
2. Find the laptop's IP (`ipconfig` on Windows).
3. Start the app, browse from other phones on the same hotspot.
4. Note: QR codes won't work (they encode the church router IP), but you can type the URL manually.

### Home WiFi

1. Connect the laptop to home WiFi, find the IP, start the app.
2. Browse from any phone on the same WiFi.
3. Again, QR codes will point to the church router IP — use the URL manually for home testing.

### Windows Firewall

If phones can't reach the app, add a firewall exception for port 5000:

1. **Windows Defender Firewall** > **Advanced settings** > **Inbound Rules** > **New Rule**
2. **Port** > TCP > `5000` > **Allow** > All profiles > Name: `FRCA Election`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Phone can't connect to WiFi | Check the WiFi password. Move closer to the router. |
| Phone connects but page doesn't load | Check the laptop's IP matches the voting base URL. Check Windows Firewall. |
| "Connection refused" error | Make sure `python app.py` is running. Check the port number. |
| Laptop got a different IP | Check that the DHCP reservation is configured and the MAC address matches. |
| Phone shows "no internet" | Expected — the router has no internet. The voting app still works. |

## Changing the IP After Printing

If you need to change the Voting Base URL after code slips have been printed:

1. Update the URL in the admin Setup page.
2. **Delete all codes** and regenerate them.
3. **Reprint all code slips** — the old QR codes encode the old URL and will not work.

## Packing List for Election Day

- [ ] Laptop (charged) + charger
- [ ] WiFi router + power adapter
- [ ] Ethernet cable
- [ ] Power board + extension lead
- [ ] Projector + HDMI cable (if using)
- [ ] Printed code slips (enough for all rounds)
- [ ] Printed paper ballots
- [ ] Attendance register + pen
- [ ] This setup guide (printed)

## Configuring the GL.iNet Flint 2 Router for Captive Portal

The Flask app is ready to serve captive portal auto-popup requests, but the
router must be configured to redirect all DNS and HTTP traffic to the laptop.
This is a one-time setup.

### Prerequisites

- GL.iNet GL-MT6000 "Flint 2" router
- Laptop connected to the router via Ethernet (use a USB-C to Ethernet
  adapter if your laptop does not have a built-in Ethernet port)
- A static IP assigned to the laptop (e.g. `192.168.8.100`) — configure this
  via the router's DHCP reservation feature, or by setting a static IP on the
  laptop's network adapter

### Step 1 — Initial router setup

1. Unbox the Flint 2 and plug in power
2. Connect your laptop to the Flint 2 via Ethernet (LAN port)
3. Open a browser and navigate to `http://192.168.8.1`
4. Complete the initial setup wizard:
   - Set an admin password (remember this)
   - Set the WiFi network name (SSID) to `ChurchVote`
   - Leave the WiFi password blank (open network) OR set a simple password
     such as `vote2026` if you prefer
   - **Skip the internet connection step** — the router will NOT be connected
     to the internet
5. Save and wait for the router to apply the settings

### Step 2 — Verify laptop IP

1. Make sure your laptop is connected to the Flint 2 via Ethernet
2. On the laptop, check the IP address:
   - **Windows:** open Command Prompt, type `ipconfig`, look for the Ethernet
     adapter's IPv4 address
   - **Mac:** open Terminal, type `ifconfig | grep inet`
   - **Linux:** type `ip addr`
3. The laptop should have an IP in the `192.168.8.x` range
4. Configure a DHCP reservation in the Flint 2 admin panel so the laptop
   always receives `192.168.8.100`:
   - Go to `Network` > `LAN` > `Address Reservation`
   - Add a reservation for the laptop's MAC address pointing to
     `192.168.8.100`
   - Save

### Step 3 — Enable captive portal DNS hijacking

This step configures the router's DNS server (dnsmasq) to resolve ALL domain
names to the laptop's IP. Without this, phones that join the WiFi will not
trigger the captive portal auto-popup.

1. In the Flint 2 admin panel, go to `System` > `Advanced Settings` (this
   opens the LuCI interface — the underlying OpenWRT admin)
2. Log in with the same admin password
3. Go to `Network` > `DHCP and DNS`
4. Scroll to the `Resolv and Hosts Files` section
5. Find the `Additional DNS` or `Advanced Settings` section
6. Add a custom dnsmasq option:

   ```
   address=/#/192.168.8.100
   ```

   This tells dnsmasq to resolve every domain name (`#` is the wildcard) to
   the laptop's IP address.
7. Save and apply

**Alternative via SSH (faster if you are comfortable with SSH):**

```bash
ssh root@192.168.8.1
uci add_list dhcp.@dnsmasq[0].address='/#/192.168.8.100'
uci commit dhcp
service dnsmasq restart
exit
```

### Step 4 — Enable captive portal on the laptop (Windows)

The laptop needs port forwarding and firewall rules so that phones' captive
portal probes (ports 80 and 443) reach the Flask app on port 5000.

1. Right-click `captive-portal-on.bat` → **Run as administrator**
2. This is a one-time step per session — the rules survive until you reboot
   or run `captive-portal-off.bat`

### Step 5 — Configure DHCP option 114 (Captive Portal API)

This tells phones explicitly that the network has a captive portal, which is
more reliable than relying on HTTP probe detection alone.

Via SSH:

```bash
ssh root@192.168.8.1
uci add_list dhcp.lan.dhcp_option='114,http://192.168.8.100/api/captive-portal'
uci commit dhcp
service dnsmasq restart
exit
```

This is a one-time configuration — the setting persists across router reboots.

### Step 6 — Test the captive portal

1. Make sure the Flask app is running on the laptop:
   ```bash
   start.bat      # Windows
   ```
2. On your phone, disconnect from any other WiFi
3. Connect to the `ChurchVote` network
4. Within a few seconds, the phone should automatically open a popup browser
   showing the voting app's code entry page
5. If the popup does not appear:
   - Open your phone's browser manually and navigate to any website (e.g.
     `http://example.com`) — you should be redirected to the voting app
   - If even this fails, check that the dnsmasq wildcard is applied correctly
     and that the Flask app is running

### Cleaning up after the demo

Run `captive-portal-off.bat` as administrator to remove the port forwarding
and firewall rules from the laptop. This is important on a shared or work
laptop — do not leave ports open when the election app is not in use.

### Fallback behaviour

Even with the captive portal configured correctly, a small number of phones
may not trigger the auto-popup (e.g. some older Android devices, phones with
DNS-over-HTTPS enabled). For these cases, the printed code slip includes a
QR code and fallback URL. Voters can always reach the ballot by scanning the
QR code if the auto-popup does not appear.

### Troubleshooting

| Problem | Solution |
|---------|----------|
| Popup appears but shows a blank page | The dnsmasq wildcard is working, but the Flask app is not responding. Verify the laptop has IP `192.168.8.100` and the app is listening on `0.0.0.0:5000`. |
| Popup does not appear at all on iOS | iOS 18+ may have changed its CPD behaviour. Fall back to the QR code on the code slip. |
| Android shows "no internet" notification | This is normal. The captive portal popup should still appear. Tap the WiFi notification to open the captive portal manually. |
| Laptop keeps disconnecting from router | Check the Ethernet cable and adapter. Try a different USB-C port if using an adapter. |
| `captive-portal-on.bat` fails | Make sure you right-clicked → Run as administrator. |
