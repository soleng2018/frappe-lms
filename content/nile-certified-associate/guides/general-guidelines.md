# Before You Start: General Guidelines

## 📌 Objective

Understand the remote lab environment and the ground rules you'll follow across every lab in this course before you begin your first configuration task.

## 🌐 Lab Topology

```text
Router (RADIUS + DHCP)
  └─ Zero Trust Fabric: Switch ── AP
       ──▶ Mac OSX PC      VNC · wired
       ┄┄▶ Windows PC 1    RDP · wireless
       ┄┄▶ Windows PC 2    RDP · wireless
```

`──▶` Wired, `┄┄▶` Wireless

> **Note:** You are given three client devices — two Windows PCs (wireless only) and one Mac OSX PC (wired only). Most labs in this course use only two of the three; some advanced labs later on will use all three at once.

## 🔧 Guidelines

### 💻 Remote Lab Access

- You'll be given access to two remote PCs, both delivered straight to your browser — no apps to install:
  - A **Windows PC**, accessed via **RDP**, used for wireless labs.
  - A **Mac OSX PC**, accessed via **VNC**, used for wired labs.
- You'll receive two separate passwords: one to access the lab URLs, and a separate operating system login password — the OS password is also used to log in via RDP, and is otherwise only needed in one specific lab.

### 🔗 One Portal to Use

- All configuration for every lab happens in the **Nile Portal**. You won't need to log into any other admin system.

### 🏷️ Use the Exact Names Given

- Each lab runs in its own isolated RF environment, so use the names already shown in the instructions (e.g. `ACME SSO`, `ACME Guest`) rather than inventing your own. In some labs, a segment name must match exactly what's configured on the RADIUS server, so precision matters.

### ✅ Follow Steps in Order

- Carefully perform each step as described — don't skip ahead. Steps build on each other within a lab, and some labs build on earlier labs (for example, the webhook/ITSM lab assumes the PSK SSO lab has already been completed).

### 🔍 Verify Before Moving On

- Every lab ends with a Verification Criteria section — confirm each condition there.

### 🛠️ Use the Built-in Troubleshooting Tool

- Under **Devices** in the Nile Portal, the `RUN TEST` button shows ping/ARP results and authentication events — use it whenever a step doesn't behave the way you expect.

### 📓 Take Notes and Complete the Quiz

- Jot down any issues, questions, or steps you find important for future reference or troubleshooting.
- Take the end-of-course quiz seriously — it helps reinforce what you've learned and highlights areas for review.
