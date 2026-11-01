# Requirements
This document covers the requirement needed to build the learning management app

## Goal
The goal of this leraning management system is to certify our students for a hands on lab. Following is what we need to achieve';
1. Students watch a video (YouTube) and take a quiz
2. Students follow a lab guide and take a quiz
3. On succesful completion (80% or higher) they get a certificate
4. Different Managers can track the progress of their student and ideally get a monthly report

## Requirements
Following are the requirements
1. All Students and Teacher need to authenticate via an IDP using OIDC. The IDP needs to be configured by this script. A global API will be provided
2. The LMS (Frappe - see Resources section below) needs to be configured via the API using this script as well
3. Customize the look and feel with the branded colors and logos  
4. Define a format to create the guides. Ideally i want to use store the guides in git and then be able to push the file to Frappe
5. Ability to back up all the content so i can recover the application if the server fails
6. All secrets and parameters needed should be in a single flile. This includes the master API tokens, URL for the app, secrets etc.
7. Everything needs to run as a docker container for now
8. This server already has traefik as the reverse proxy so just add labels. See a sample compose file in /home/nova/lms

## Instructions
1. The frappe installation on this server can be considered as dev
2. You can delete things you create but cannot delete other running containers
3. In Authentik, you can delete what you create but cannot delete other items
4. Students in the app will be identified by a group name called NileWorkshopNAdmin (where N can be 1,2,3..) and admins will be identified by a group called hol-admins. this groups already exist so Frappe just needs to use them

## Resources
* Frappe Repo - https://github.com/frappe/lms
* Frappe Documentation - https://docs.frappe.io/learning/get-started/installation
* Frappe API - https://docs.frappe.io/framework/user/en/introduction
* Branding and design system - see the `brand/` folder