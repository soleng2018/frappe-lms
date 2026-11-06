# Lab Assignment: Setting Up PSK Wireless SSID

## 📌 Objective

Configure a secure PSK (Pre-Shared Key) SSID on the Nile Portal, connect a test client to the SSID, and verify successful connection and network access.

[🔗 Go to Nile Portal](https://u1.nile-global.cloud)

## 🔧 Task Instructions

### Step 1: DHCP Configuration

- Navigate to **Network Setup → DHCP**.
- Select `Nile DHCP` as the server type.
- Create a new DHCP scope for this PSK SSID:
  - **Pool Name** - `IOT-Scope`
  - **Network** - `192.168.10.0/24`
  - **DNS Server** - `4.2.2.1`
  - Click **Save**

### Step 2: Segment Creation

- Go to **Network Setup → Segments**.
- Create a new segment named `IOT-Seg`:
  - Select the **Service Area**.
  - Choose **HoL** and Click **OK**
  - No Authentication source needs to be configured
  - Select the **DHCP scope (Nile DHCP)** for the clients.
  - Select the **Subnet IOT-Scope** that was created in the previous Step
  - Click **Save**

### Step 3: Wireless SSID Configuration

- Navigate to **Network Setup → Wireless**.
- Click on the ➕ icon to add a new SSID.
- Configure the following:
  - **SSID Name:** Define anything you like, ensure it is unique to you. e.g, `ACME IOT` (use your own company/tenant name)
  - **Type:** `Personal`
  - **Security:** `WPA2`
  - **Pre-shared key:** `12345678`
  - **Segment:** `IOT-Seg` (or any other name you may have used)

### Step 4: Connectivity Testing

- If you are conducting this lab remotely, you should have received a URL (and a username/password) to connect to a windows device
- Use a wireless device to connect to the new SSID.
- Verify you can access the Internet

### Step 5: Monitoring and Troubleshooting

- Nile provides a single button to troubleshoot clients. When executed it runs a variety of tests and displays the results. It also gives the option to run some on-demand tests like Speed Test thus giving a 360 view of the client.
- Navigate to **Devices → Click on your Wireless Client**
- Click on **RUN TEST** (top right hand corner of the screen)
- Take Note of the **Ping and ARP ping** status
- Disconnect the client and enter an incorrect pre-shared key
- Navigate to the **Dashboard** and note down what you see

### Step 6: Testing Incorrect PSK Behavior

- Go back to your wireless client. On Windows, click the Wi-Fi icon in the taskbar, right-click on the SSID you connected to earlier, and select **Forget**.
- Reconnect to the same SSID, but this time deliberately enter an **incorrect Pre-Shared Key**.
- Navigate to **Devices** in the Nile Portal, then click on your device's **MAC address** to land on its device details page.
- In the **Events** table on that page, take note of the error shown.
- Be patient — it can take a minute or two for the dashboard to reflect the issue.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- SSID is broadcasting and visible to client devices.
- Devices are receiving an IP address from the respective DHCP scope for this segment.
