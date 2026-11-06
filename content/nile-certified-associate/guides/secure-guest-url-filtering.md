# Lab Assignment: Setup Nile Guest Service SSID with URL Filtering

## 📌 Objective

Enable and test a Nile Guest Service SSID, configure URL filtering, and validate access restrictions for guest users.

## 📖 About Nile Guest Service

Nile Guest Service is a modern, secure solution designed to provide guest internet access while isolating guest devices from an organization's internal network. It is part of the Nile Access Service (Network as a Service, NaaS) and addresses the security and management challenges associated with traditional guest network setups.

All guest traffic is securely tunneled to a cloud-based Point of Presence (PoP) closest to the location, ensuring low latency and optimal performance. By utilizing Nile Guest Service, organizations can provide secure and reliable internet access to guests without compromising their internal network's security.

**Key Features:**

- **Zero Trust Security:** Guest traffic is completely isolated from corporate resources, preventing unauthorized access and lateral movement within the network.
- **User-Friendly Experience:** The service offers a smooth experience for guests, reducing the need for help desk support.
- **Operational Efficiency:** It simplifies guest network management by eliminating the need for complex configurations like VLANs and DHCP.
- **Scalable Solution:** Easily adapts to multi-site deployments without added complexity.
- **Compliance Management:** Helps organizations manage compliance issues related to guest access.

## 🔧 Task Instructions

### Step 1: Navigate to Wireless and Edit SSID

- Navigate to **Network Setup → Wireless**.
- Edit the `"Nile"` SSID.
- Replace the SSID name with `ACME Secure Guest`.

### Step 2: Set Authentication Type

- Set the **Authentication Type** to `Click through`.

### Step 3: Configure URL Filtering

- Click on the **URL Filtering** tab.
- Select a filtering level: `Low`, `Moderate`, or `Strict`.
- Refer to this guide: [Nile URL Filtering Documentation](https://docs.nilesecure.com/url-filtering)

### Step 4: Advanced URL Filtering (Optional)

- Click on the **Advanced** tab.
- Add a blocked URL such as `https://www.youtube.com`.
- You may also add allowed URLs as needed.

### Step 5: Connect and Test

- Connect a device to the SSID.
- Take note of the IP address assigned to the device using `ipconfig` via Command Prompt.
- Attempt to browse restricted content to verify that filtering is applied.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- Guest device successfully connects to the SSID.
- URL filtering blocks access to restricted categories or domains.
- Advanced rules take effect (e.g., https://www.youtube.com is blocked).
