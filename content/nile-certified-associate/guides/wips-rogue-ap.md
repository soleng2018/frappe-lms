# Lab Assignment: Detect a Rogue Access Point with WIPS

## 📌 Objective

Connect a client to a rogue access point that is plugged into the Nile switch, then use the Nile Portal to see how the Wireless Intrusion Prevention System (WIPS) detects the rogue AP, raises a security alert, and flags your client as misassociated.

[🔗 Go to Nile Portal](https://u1.nile-global.cloud)

## 🧭 Background

A **rogue AP** is an access point that is connected to your wired network without your approval, often broadcasting a name that looks like a real corporate SSID. Clients that join it are exposed to snooping and attacks, and the rogue AP gives an outsider a way into the wired network.

For this lab, a Raspberry Pi is already connected to a wired port on the switch and is broadcasting an SSID called `Nile-Corp`. You will play the part of an unsuspecting user who joins it.

## 🔧 Task Instructions

### Step 1: Confirm the Catch-All Rule Is Enabled

The Raspberry Pi gets onto the network because of the `Allow All MACs` rule you created in the **Setup Wired Fingerprint** lab.

- Navigate to **Network Setup → Access Management**.
- Confirm the `Allow All MACs` rule is present, with the segment set to `Guest` and the status set to `Approved`.
- In the device table, confirm that a wired device whose MAC address ends in `4d:00` is listed with the status **Approved**. This is the Raspberry Pi, and it is on the network because of that rule.
- If the rule is missing, go back to **Step 4** of the **Setup Wired Fingerprint** lab and create it.

### Step 2: Connect to the Rogue SSID

- On your wireless device (or the lab PC), open the list of Wi-Fi networks.
- Connect to the `Nile-Corp` SSID.
- When asked for the password, enter `nilesecure`.
- Your device receives an IP address from the **Guest** segment (`192.168.19.x`).

### Step 3: Generate Some Traffic

- Open a browser and browse a few websites to confirm you can reach the Internet.
- Optionally, run a speed test (for example at `fast.com` or `speedtest.net`) to generate more traffic, so your client shows up with usage in the portal.

### Step 4: Review the WIDS Summary on the Devices Page

- Navigate to **Devices**.
- At the top of the page, find the **WIDS** tile. Its legend shows **Rogue**, **Suspected Rogue** and **Misassociated**. You should see **2 clients** counted here: the rogue AP and your device.
- In the **Connection type** tile, note that the rogue AP is a **Wired** connection, because it is plugged into the switch.
- In the device table, look for:
  - A device named `nile-wips-rogue`. This is the rogue AP. Its MAC address ends in `4d:00`.
  - Your own device. Its **Error** column shows **MAC Authentication Failed**, because it joined through the rogue AP and not through the Nile network.

### Step 5: Inspect the Rogue AP

- On the **Devices** page, click `nile-wips-rogue` to open its details.
- Review the details panel:
  - **BSSID** - the wireless address of the rogue AP (it ends in `4d:01`).
  - **Ethernet MAC** - the wired address of the rogue AP (it ends in `4d:00`).
  - **Mitigation status** - shows **Rogue AP**.
  - **Connected to** - the Nile access switch and port the rogue AP is plugged into. This tells you where to go and unplug it.
- Review the **Misassociated device list** on the right. Your device is listed here with its MAC, type and OS.
- Scroll through the **Events** table and find these entries:
  - `ROGUE AP DETECTED`
  - `ROGUE AP BLOCKED`
  - `ROGUE AP OFFLINE`
  - `CLIENT ASSOCIATED TO ROGUE AP`, followed by your device's MAC address

### Step 6: Inspect Your Own Client

- Navigate back to **Devices** and click your device.
- In the details panel, note the **Auth Type** (`STA MAC AUTH`), **IP** and **Last seen**.
- In the **Connectivity** diagram, note that your device is linked to the rogue AP (shown in red), and that the rogue AP is linked to the **Network** (shown in green).
- In the **Events** table, find `CLIENT ASSOCIATED TO ROGUE AP`, along with the `MAC Authentication Failed` and `Client Disconnected` events.

### Step 7: Review the Security Alert

- Navigate to **Alerts**.
- Find the newest alert, with the type **Security** and the status **Created**.
- Read the **Alert details**. They give you:
  - The BSSID and MAC address of the rogue AP.
  - The SSID it is broadcasting.
  - The location where it was detected and for how long.
  - The switch name, port and serial number it is connected to.
  - Whether Nile has blocked the device.
- Click **More Details** to open the full alert.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- Your device connected to `Nile-Corp` and received an IP address from the **Guest** segment.
- The **WIDS** tile on the **Devices** page shows the rogue AP and your device.
- `nile-wips-rogue` shows a **Mitigation status** of **Rogue AP**, and the switch port it is connected to.
- Your device appears in the **Misassociated device list** of the rogue AP.
- A **Security** alert for the rogue AP appears under **Alerts**.
