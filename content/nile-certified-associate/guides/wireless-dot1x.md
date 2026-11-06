# Lab Assignment: Setting Up 802.1X Wireless SSID

## 📌 Objective

Configure a secure wireless SSID with 802.1X authentication using RADIUS, and validate connectivity for Employees.

[🔗 Go to Nile Portal](https://u1.nile-global.cloud)

## 🔧 Task Instructions

### Step 1: DHCP Configuration

- Navigate to **Network Setup → DHCP**.
- Select `Nile DHCP` as the server type.
- Create an Employee Scope:
  - **Pool Name** - `Employee`
  - **Network** - `192.168.11.0/24`
  - **DNS Server** - `4.2.2.1`
  - Click **Save**

### Step 2: Authentication (RADIUS) Setup

- Go to **Network Setup → Authentication**.
- Click on the ➕ icon to add a new RADIUS server:
  - **Name** - `myRADIUS`
  - **Geoscope** - `HoL`
  - **Host 1** - `172.16.254.2`
  - **Shared Secret** - `nile123`
  - **Port** - `1812`
- Click **"Verify Hosts"** to ensure it's reachable (this can be done before saving):
  - Test credentials:
    - **Username:** `bob`
    - **Password:** `hello`
- Click on **"DISPLAY NAS IP'S"**.
  - These are the IP addresses that must be allowed on the RADIUS server side. For this lab, the RADIUS server has already been set up for you, but in a production deployment, you would need to add these NAS IPs to your RADIUS server's client list.
- Click **Save**

### Step 3: Segment Creation

- Go to **Network Setup → Segments**.
- Create a new segment named `Employee`:
  - Select the **Service Area**.
  - Choose **HoL** and Click **OK**
  - Set Authentication source to `myRADIUS`
  - Select the **DHCP scope (Nile DHCP)** for the clients.
  - Select the **Subnet Employee** that was created in the previous Step
  - Click **Save**

### Step 4: Wireless SSID Configuration

- Navigate to **Network Setup → Wireless**.
- Click on the ➕ icon to add a new SSID.
- Configure the following:
  - **SSID Name:** `ACME Employee`
  - **Type:** `Enterprise`
  - **Security:** `WPA2`
  - **Segments:** Select the `Employee` segment.
  - Click **Save**

### Step 5: Connectivity Testing

- If you are conducting this lab remotely, you should have received a URL (and a username/password) to connect to a windows device
- Use a wireless device to connect to the new SSID.
- Test the following logins:
  - **Employee Login:** `employee` / `nilesecure`
- Confirm device placement into the correct segment.
- If the device fails to connect, troubleshoot it by navigating to **Devices → Click on your Wireless Client --> Events**

### Step 6: Testing Incorrect Credentials Behavior

- Go back to your wireless client. On Windows, click the Wi-Fi icon in the taskbar, right-click on the SSID you connected to earlier, and select **Forget**.
- Reconnect to the same SSID, but this time deliberately enter an **incorrect username/password**.
- Navigate to **Devices** in the Nile Portal, then click on your device's **MAC address** to land on its device details page.
- In the **Events** table on that page, take note of the error shown.
- Be patient — it can take a minute or two for the dashboard to reflect the issue.

### Step 7: Advance Troubleshooting

- Navigate to the client you just connected with the wrong RADIUS credentials: **Devices → Your Device**.
- On the device details page, click **"Advanced"** (next to "Show All") to open the detailed Events modal.
  - The **Events** tab shows detailed, per-transaction data for DNS, DHCP, and RADIUS — not just the summary events on the main page.
  - Example: you can see the entire **DHCP DORA exchange** (Discover, Offer, Request, Ack) for the device's IP assignment.
  - Example: you can see the full **RADIUS exchange** between the access point/switch and the RADIUS server, including the request that was rejected due to the incorrect credentials.
- Click on the **"Auth Trace"** tab.
  - This shows every **EAP message** exchanged between the client (HE), the Nile access device (AS), and the authentication server during 802.1X authentication.
  - For a successful authentication, you'll see a sequence of EAP Request/Response messages (e.g. EAP PEAP) ending in a **"Station Authorized"** event.
  - For the failed attempt with bad credentials, compare the trace to see where the exchange differs or terminates.
- Use the **"Auth Trace"** tab, not the **"Radius Transactions"** tab, to diagnose authentication issues in this lab.
  - The **"Radius Transactions"** tab is used to see the **Nile RADIUS** logs. In this lab, authentication goes to your own RADIUS server (`myRADIUS`), so those logs are not where you will find the result.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- SSID is broadcast and visible to client devices.
- RADIUS server passes the verification test.
- Employee credentials work as expected.
- Devices are assigned to their correct segments.
