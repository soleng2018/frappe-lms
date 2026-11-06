# Lab Assignment: Creating Support Tickets from myNile via Webhooks to an ITSM like ServiceNow

## 📌 Objective

Enable end users to create support tickets directly from the my.nilesecure.com (myNile) portal by integrating Nile with an ITSM platform like ServiceNow using webhooks.

## 🔧 Task Instructions

### Step 1: Configure Nile Portal

- Log in to the Nile portal as an admin.
- Navigate to **Settings → Global Settings → Integration**.
- Click `"+ Setup Integration"`.
- Click `"Web hook"`.

### Step 2: Provide Webhook Information

- Provide the necessary information as below:
  - **Name:** `Any name`
  - **URL** - `https://automation.nilenetworks.com/webhook/mynile`
  - **Token** - `5110d57f-af94-47fb-9914-a2526af116ef`
- Click **Next**.
- Toggle `My Nile Incidents` to **ON**.

### Step 3: Trigger a Ticket from my.nilesecure.com

- Navigate to the PC and connect to the **ACME SSO** SSID.
- Open a browser and navigate to `my.nilesecure.com` and click on **"Need more help"** in the top-right corner to create a service ticket.
- Provide the necessary information, such as email, title, issue description, and submit the ticket.
- Click the camera icon (📷) in the "Report incident" form to take a screenshot of the page and attach it to the ticket.

### Step 4: View the Ticket

- Go to `https://automation.nilenetworks.com/webhook/mynile-tickets` to view the ticket that was created via the webhook.

## ✅ Verification Criteria

Ensure the following conditions are met before considering the lab complete:

- Navigate to the PC and connect to the **ACME SSO** SSID.
- Open a browser and navigate to **my.nilesecure.com** and click on **"Need more help"** in the top-right corner to create a service ticket.
- Provide the necessary information, such as email, title, issue description, and submit the ticket.
- Click the camera icon (📷) in the "Report incident" form to take a screenshot of the page and attach it to the ticket.
