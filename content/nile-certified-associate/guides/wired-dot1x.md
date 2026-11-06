# Lab Assignment: Wired 802.1X Authentication Test

## 📌 Objective

Test Wired 802.1X Authentication by using the same RADIUS configuration and segment settings previously created for the Wireless 802.1X SSID.

## 🔧 Task Instructions

### Step 1: Verify RADIUS Configuration

- Confirm that the **RADIUS server** configured for the **Wireless 802.1X SSID** is already available under: **Network Setup → Authentication**.
- Ensure the server is verified and correctly configured.

### Step 2: Verify Segment Setup

- Confirm that the **Employee Segment** configured for wireless devices is available under: **Network Setup → Segments**.
- Verify the segment name is exactly `Employee` (case sensitive).
- Make sure the correct **DHCP scope** and **RADIUS server** are attached.

### Step 3: Connect a Wired Device

- Connect a wired 802.1X-capable device (e.g., a Windows or macOS laptop) to the switch.
- The device should automatically attempt 802.1X authentication using the existing RADIUS server.
- Use the following credentials to authenticate:
  - **Employee Login:** `employee` / `nilesecure`
- 📝 **Note:** Since PEAP credentials are being used, enter the PC username and password when prompted. These are provided as part of the scheduling email.

### Step 4: Verify Segment Assignment

- Once authenticated, confirm that the device is placed into the **Employee Segment** by navigating to **Devices** and clicking on your device in the table to view its details.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- Device connects successfully and authenticates using 802.1X.
- Device is placed in the correct segment (Employee).
- Device appears under **Access Management → Devices** with the correct segment assignment.
