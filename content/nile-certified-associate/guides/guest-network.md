# Lab Assignment: Setup Custom Guest Captive Portal SSID

## 📌 Objective

Create a Guest Wi-Fi SSID with a custom captive portal, configure it with an external DHCP server, and customize branding (logo, colors, background).

[🔗 Go to Nile Portal](https://u1.nile-global.cloud)

## 🔧 Task Instructions

> **Note:** Go to Nile Portal and click "Get started" on the right side of the "self guide HOL - Create Guest SSID"

### Step 1: DHCP Configuration

- Navigate to **Network Setup → DHCP**.
- Do **NOT** use Nile DHCP for this task.
- Click on ➕ icon to Add a new external DHCP server:
  - **Name** - `External DHCP` (put a name of your choice)
  - **Geo scope** - `HOL`
  - **Host** - `172.16.253.2`
  - **Subnets** - Click on ➕ icon to add a second new subnet
    - **Subnet** - `192.168.19.0/24`
    - **Router** - `192.168.19.1`
  - Click **Save**

### Step 2: Guest Portal Setup

- Navigate to **Network Setup → Authentication**.
- Click ➕ symbol → Choose `"Nile Guest"`
- Configure the following:
  - **Name** - `ACME Guest Portal`
  - **Geo scope** - `HOL`
  - Click the drop-down → Choose `"Access code"`
  - Toggle **"Use generic access code"**
  - Click **Save**
  - Edit the Guest Portal by clicking it
- On the table, click the ➕ icon to add an entry
- Enter `12345678` and Click the ➕ icon
- Click **Save**

### Step 3: Segment Creation

- Go to **Network Setup → Segments**.
- Create a new segment named `Guest`:
  - Select the **Service Area**.
  - Choose **HoL** and Click **OK**
  - Set Authentication source to `Guest Portal` (the name of your guest portal created in the previous step)
  - Select the **DHCP scope (External DHCP or your DHCP server name)** for the clients.
  - Select the **Subnet 192.168.19.0/24** that was created in the previous Step
  - Click **Verify DHCP**
  - Click **Save**

### Step 4: Wireless SSID Configuration

- Navigate to **Network Setup → Wireless**.
- Click the ➕ icon to create a new SSID.
- Configure the following:
  - **Type** - `Captive Portal`
  - **Name** - `ACME Guest` (Choose any distinctive Name)
  - **Security** - `Open`
  - **Segments** - `Guest` (Created in the previous step)

### Step 5: Customize the Guest Portal

- Navigate to **Global Settings → Guest Portal**.
- Click on your portal and customize:
  - Upload your company logo
  - Set background image
  - Choose brand colors

### Step 6: Connectivity Testing

- If you are conducting this lab remotely, you should have received a URL (and a username/password) to connect to a windows device
- Use a wireless device to connect to the new SSID.
- When the Captive Portal appears, enter the access code `12345678` to authenticate.
- Verify you can access the Internet

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- SSID is visible.
- Captive Portal is displayed on connection.
- Branding is visible and applied correctly on the portal page.
- Client successfully authenticates with the access code and reaches the Internet.
