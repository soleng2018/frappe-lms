# Lab Assignment: Onboard a Wired Device Using the Fingerprint Rule

## 📌 Objective

Automatically onboard a wired device based on its fingerprint (OS/device type) by applying fingerprint-based rules, without requiring 802.1X or manual registration.

## 🔧 Task Instructions

### Step 1: Pre-Lab Cleanup (Reset Previous Lab State)

Before starting this lab, clear out the 802.1X credentials and device record left over from the previous wired lab so the device can be classified fresh by fingerprint.

- Open a Terminal window on the Mac and verify the stored 802.1X (PEAP) credentials exist:
  `security find-generic-password -D "802.1X Password"`
- Delete the credentials:
  `sudo security delete-generic-password -D "802.1X Password"`
- Run the same find command again to confirm the credentials are gone (it should return no match):
  `security find-generic-password -D "802.1X Password"`
- ⚠️ **Critical step:** In the Nile Portal, navigate to **Devices** → click your device → **Action** → **Disconnect**.
- In the Nile Portal, remove the device record: navigate to **Network Setup → Access Management**, select the device's MAC address, and delete it.
- On the Mac, go to **Settings → Network**, select the USB dongle, and click **Make Active**.
- Verify the device reappears in the Nile Portal under **Network Setup → Access Management** with a status of **Waiting for approval**.

### Step 2: Segment Reuse & Update

- Navigate to **Network Setup → Segments**.
- Verify that the `IOT-Seg` segment exists, as it will be reused for this lab.

### Step 3: Fingerprint Rule Setup

- Navigate to **Network Setup → Access Management** and click the **+** icon at the top right of the table to create a new rule.
- In the **Add device** dialog, fill in the rule:
  - Under **Select***, choose `Fingerprint`.
  - Under **Select segment**, choose `IOT-Seg`.
  - Under **Fingerprint***, select `Mac OS X or macOS` (or `Windows OS`, depending on your device).
  - Set **Status*** to `Approved`.
  - Click **SUBMIT**.

### Step 4: Catch-All Rule Setup

- Navigate to **Network Setup → Access Management** and click the **+** icon at the top right of the table to create another rule.
- In the **Add device** dialog, fill in the rule:
  - Under **Select***, choose `Allow All MACs`.
  - Under **Select segment**, choose `Guest`.
  - Set **Status*** to `Approved`.
  - Click **SUBMIT**.
- This catch-all rule ensures any device that doesn't match the fingerprint rule still gets placed into the **Guest** segment instead of being left unapproved.

### Step 5: Device Connection

- Connect your wired laptop or desktop to the switch.
- The device will first match the `ALL` rule and land in the **Guest** segment.
- Once the system fully fingerprints the device, it will automatically move it to the **IOT-Seg** segment, without any user action.

⏳ **Note:** Fingerprinting can take some time to complete and move the device to the correct segment. Rather than waiting here, continue on with the other labs and come back to this lab at the end to verify the device has landed in the **IOT-Seg** segment.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- Device is fingerprinted and recognized correctly.
- Auto-approved rule is triggered and device is placed in the updated segment.
- Device appears in **Access Management → Devices** with its type (Windows/macOS) and correct segment.
