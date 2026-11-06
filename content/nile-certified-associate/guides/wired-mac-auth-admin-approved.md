# Lab Assignment: Wired MAC Auth - Admin Approved

## 📌 Objective

Approve a wired device manually as an admin by assigning it to a segment, confirm that its authentication source shows **Admin Approved**, and verify that the device has network access.

[🔗 Go to Nile Portal](https://u1.nile-global.cloud)

## 🔧 Task Instructions

### Step 1: Approve the Wired Device

- Navigate to **Network Setup → Access Management**.
- Look for a wired device whose MAC address does **NOT** end in `4d:00`.
- Select it.
- Click the **pencil (Edit)** icon ![pencil icon](../images/wired-mac-auth-edit-icon.png).
- Open the **Select segment** drop-down and select `IOT-Seg`.
- Open the **Status** drop-down and select `Approved`.
- Click **SUBMIT**.

### Step 2: Show the Auth Source Column

- Click the **columns** icon ![columns icon](../images/wired-mac-auth-columns-icon.png), to the left of the search bar.
- Select **Auth Source** and click **Apply**.
- A new column called **Auth Source** appears. Your device is shown as **Admin Approved**.

### Step 3: Verification Test

- Navigate to **Devices** and click on your wired device to open its device details page.
- Click on **RUN TEST** (top right hand corner of the screen).
- Take note of the **Ping and ARP ping** status.

⏳ **Note:** Client metrics data can take a couple of minutes to populate, so **RUN TEST** may not work right away. If it fails, wait a couple of minutes and try again.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- The device status is **Approved** and it is placed in the `IOT-Seg` segment.
- The **Auth Source** column shows **Admin Approved** for your device.
- The **RUN TEST** results on the device details page are successful.
