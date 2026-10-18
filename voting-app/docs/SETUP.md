# Hardware and Network Setup

> **Before following these instructions, please read the disclaimer in the main README. You are fully responsible for the correct setup and operation of this software.**

This document explains how to install the app, set up the laptop and WiFi router for the election, and test at home beforehand.

## What You Need

| Item | Notes |
|------|-------|
| Laptop | Windows 10/11, 64-bit. No Python needed when you use the installer. |
| WiFi router | GL.iNet GL-MT6000 "Flint 2". Other routers may work but are not tested. No internet connection needed. |
| Ethernet cable | Cat5e or Cat6, 1-2 metres (USB-C to Ethernet adapter if the laptop has no port) |
| Power board | For laptop and router |
| Extension lead | Depending on hall layout |
| Projector + HDMI cable | For displaying live results (optional) |

The setup below gives a fixed network: router at `10.0.0.1`, laptop always at `10.0.0.2`, voting URL `http://10.0.0.2`. Code slips printed in advance depend on that address, so keep it the same from printing to election night.

## Step 1: Install the app

1. Download `FRCA-Election-Setup-<version>.exe` from the
   [Releases page](https://github.com/jdemooijau/frca_election_app/releases).
2. Run it. Windows SmartScreen may say "Windows protected your PC" because
   the installer is not code-signed. Click **More info**, then **Run anyway**.
3. Accept the administrator prompt. The installer needs it to add the
   firewall rule.

The installer:

- installs the app to `C:\Program Files\FRCA Election\`,
- keeps all election data in `C:\ProgramData\FRCA Election\data`,
- adds one firewall rule, **FRCA Election**, that lets devices on the
  `10.0.0.x` network reach the app on ports 80 and 5000 (and nothing else),
- adds two Start menu entries: **FRCA Election** (starts the app) and
  **FRCA Election data folder**.

Start the app from the Start menu. A console window opens and shows the
version, the data folder and the URLs, and the admin page opens in your
browser. Closing the console window stops the app. On first launch the setup
page asks for your congregation name, WiFi details and a new admin password
(the default is `admin`).

**Upgrading:** run the newer installer. Your data stays where it is. The
first time the new version starts it copies the database to
`data\backups\` before updating it.

**Uninstalling:** use Windows **Settings > Apps**. The data folder is kept;
delete it yourself if you no longer need it.

**Moving from a source checkout:** close both copies of the app, then copy
the contents of your old `voting-app\data` folder into
`C:\ProgramData\FRCA Election\data`.

## Step 2: Set up the router

### 2a. First-time router setup

1. Plug in the Flint 2 and connect the laptop to one of its LAN ports with
   the ethernet cable.
2. Open `http://192.168.8.1` and complete the setup wizard:
   - set an admin password (remember it),
   - set the WiFi name, e.g. `ChurchVote`, and a simple password such as
     `vote2026` (or leave it open),
   - **skip the internet connection step**.
3. Turn on SSH if it is not on already: **System > Advanced Settings** (or
   **System > Security**, depending on firmware) and enable SSH access.

### 2b. Find the laptop's ethernet MAC address

In Command Prompt, run `getmac /v`. Use the **Physical Address** on the
line for the ethernet adapter (not WiFi), e.g. `A0-B1-C2-D3-E4-F5`.
Write it with colons: `A0:B1:C2:D3:E4:F5`.

### 2c. Run the setup script

The script is in the app's source under `voting-app/router/flint2-setup.sh`
(also attached to each release). From Command Prompt on the laptop:

```cmd
scp flint2-setup.sh root@192.168.8.1:/tmp/
ssh root@192.168.8.1 sh /tmp/flint2-setup.sh A0:B1:C2:D3:E4:F5
```

Log in with the router admin password. The script:

- moves the router's network to `10.0.0.1/24`,
- reserves `10.0.0.2` for the laptop's MAC address,
- with `--captive-portal` at the end, also sets up the optional auto-popup
  (see below); without it, it removes those settings again.

It prints each change, saves, and restarts the router's network, so the
SSH session drops at the end. That is expected. The script is safe to run
again, e.g. with a different laptop. From now on the router is at
`10.0.0.1` (use `root@10.0.0.1` next time).

### 2d. Check the laptop's address

Unplug the ethernet cable, wait 10 seconds, plug it back in. Run `ipconfig`
and confirm the ethernet adapter has IPv4 address `10.0.0.2`.

## Step 3: Configure the app

1. In the admin page, open **Setup** (or **Settings**).
2. Set the **WiFi Network Name** and **WiFi Password** to match the router.
3. Leave the **Voting Base URL** at `http://10.0.0.2` unless you have a
   reason to change it.
4. Save.

## Step 4: Check the network

Do this before printing code slips, with the laptop connected to the
router.

1. On the Setup page, click **Check the network**.
2. The page shows the laptop's addresses and checks them against the voting
   URL. If it says **"Code slips printed now will not work on this
   network"**, fix the address (Step 2d) before printing.
3. It also checks that the app answers on port 80, which `http://10.0.0.2`
   uses. If it warns that the app is not answering on port 80, look at the
   console window: it says what is holding port 80.
4. Join the voting WiFi on a phone and scan the QR code on the page. The
   phone should show **"This phone can reach the voting app."** A phone
   that shows "no internet" is normal: the router has no internet, and the
   app still works.

## Step 5: Generate and print code slips

Generate the voting codes in the admin panel. The code slip PDF includes QR
codes with the full URL (e.g. `http://10.0.0.2/v/KR4T7N`), the WiFi name
and password, and the URL to type if a phone cannot scan.

Voters scan the QR code with the phone camera, and the browser opens with
the code filled in.

## Projector Setup

1. Connect the projector to the laptop via HDMI.
2. Open `http://localhost:5000/display` in full-screen (F11).
3. The display refreshes every second.

## Optional: Captive Portal Auto-Popup

A captive portal is the popup some phones show when they join a WiFi
network with no internet ("Sign in to network"). With it set up, some
phones that join `ChurchVote` open the voting app by themselves.

**Reality check:** this is a bonus, not a feature to promise.

- iOS phones tend to show the popup. Many Android phones do not, even when
  everything is set up correctly.
- Phones with "Private DNS" turned on bypass the router's DNS, so the popup
  never fires.
- Android phones with mobile data on may keep using mobile DNS, which is
  why the voting URL is the literal address `http://10.0.0.2`, not a name.

The QR code on the code slip stays the way in for voters.

To turn it on, run the router script with the flag:

```cmd
ssh root@10.0.0.1 sh /tmp/flint2-setup.sh A0:B1:C2:D3:E4:F5 --captive-portal
```

This points every website name at the laptop (DNS wildcard) and tells
phones where the portal is (DHCP option 114). Nothing is needed on the
laptop: the installed app already listens on port 80. Run the script
again without `--captive-portal` to turn it off.

Test: on a phone, forget the network, join `ChurchVote` again, and wait a
few seconds for the popup. If none appears, open `http://example.com` in
the browser; you should land on the voting page.

## Testing at Home

QR codes on test slips point at `10.0.0.2`. At home without the Flint 2,
type the URL by hand instead.

- **Phone hotspot or home WiFi:** connect the laptop, find its address with
  `ipconfig`, start the app, and browse to `http://<laptop-address>:5000`
  from a phone on the same network.
- The firewall rule only allows `10.0.0.x` devices. On another network,
  Windows may block phones; see **Firewall** below.
- The best home test is the real setup: Flint 2, laptop on ethernet, and the
  network check page (Step 4).

## Firewall

The installer adds the **FRCA Election** rule. To check it:

```cmd
netsh advfirewall firewall show rule name="FRCA Election"
```

It should list local ports `80,5000` and remote IP `10.0.0.0/24`. Reinstall
to restore it if it is missing.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Phone can't connect to WiFi | Check the WiFi password. Move closer to the router. |
| Phone connects but page doesn't load | Run the network check (Step 4). Check the laptop has `10.0.0.2` and the firewall rule exists. |
| Console says port 80 is in use | Another program holds port 80. Find it with `netstat -ano \| findstr :80`. If you used `captive-portal-on.bat` before, run `captive-portal-off.bat` as administrator, then restart the app. |
| Console says port 5000 is in use | Another copy of the app is running (installed or from source). Close it. |
| Laptop got a different address | Rerun the router script with the laptop's ethernet MAC (Step 2b and 2c). |
| Phone shows "no internet" | Expected. The router has no internet. The voting app still works. |
| SmartScreen blocks the installer | Click **More info**, then **Run anyway**. |

## Changing the Address After Printing

If you change the Voting Base URL after code slips have been printed:

1. Update the URL on the admin Setup page.
2. **Delete all codes** and generate them again.
3. **Reprint all code slips.** The old QR codes hold the old URL and will
   not work.

## Packing List for Election Day

- [ ] Laptop (charged) + charger
- [ ] WiFi router + power adapter
- [ ] Ethernet cable (and USB-C adapter if needed)
- [ ] Power board + extension lead
- [ ] Projector + HDMI cable (if using)
- [ ] Printed code slips (enough for all rounds)
- [ ] Printed paper ballots
- [ ] Attendance register + pen
- [ ] This setup guide (printed)

## For Developers: Running from Source

Running from source still works as before and needs Python 3.11+:

```cmd
cd voting-app
pip install -r requirements.txt
start.bat
```

`start.bat` serves on port 5000 only, and the data stays in
`voting-app\data`. For phones to reach the plain `http://10.0.0.2` URL,
port 80 must be forwarded to 5000: right-click `captive-portal-on.bat` and
**Run as administrator**.

The port forwarding is stored by Windows and **survives reboots**. Run
`captive-portal-off.bat` as administrator when you are done, especially on
a shared or work laptop. Installing the app also removes it, because it
would block the installed app from port 80.

Do not run the installed app and a source copy at the same time; the
second one finds port 5000 in use and stops.

To build the installer yourself: install
[Inno Setup 6](https://jrsoftware.org/isinfo.php), then run
`powershell -File voting-app\packaging\build.ps1`. It runs the tests and
the display-fit release gate, builds the program with PyInstaller, smoke
tests it, and writes the installer to `voting-app\packaging\dist\`.
