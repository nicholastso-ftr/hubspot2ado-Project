import azure.functions as func
import logging
import json
import os
import base64
import requests

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="/test", methods=["GET", "POST"])
def test(req: func.HttpRequest) -> func.HttpResponse:
    return process_hubspot_webhook(req)
        
def process_hubspot_webhook(req: func.HttpRequest) -> func.HttpResponse:
    try:
        logging.info('Python HTTP trigger function processed a request.')

        try:
            events = req.get_json()
        except ValueError:
            raw_body = req.get_body()
            logging.info(f"Raw Body: {raw_body}")
            return func.HttpResponse("Invalid JSON", status_code=400)

        for event in events:
            ticket_id = event.get("objectId")

            if not ticket_id:
                return func.HttpResponse("No ticket ID", status_code=400)

            logging.info(f"Ticket ID: {ticket_id}")

            # Fetch ticket details from HubSpot
            hubspot_url = f"https://api.hubapi.com/crm/v3/objects/tickets/{ticket_id}"
            hubspot_headers = {
                "Authorization": f"Bearer {os.environ['HUBSPOT_ACCESS_TOKEN']}",
                "Content-Type": "application/json"
            }

            hs_response = requests.get(hubspot_url, headers=hubspot_headers)
            hs_response.raise_for_status()

            ticket = hs_response.json()
            props = ticket.get("properties", {})

            # HubSpot ticket properties
            title = props.get("subject") or f"HubSpot Ticket {ticket_id}"
            description = props.get("content") or "No description provided"

            hs_priority = (props.get("hs_ticket_priority") or "").lower()
            priority_map = {
                "urgent": 1,
                "high": 2,
                "medium": 3,
                "low": 4
            }
            priority = priority_map.get(hs_priority, 4)

            client_id = props.get("client_id") or "ftr"
            resolution_notes = props.get("ticket_resolution_notes") or "N/A"
            create_date = props.get("createdate") or ""
            ticket_owner = props.get("hubspot_owner_id") or ""
            support_form = props.get("form_identifier") or ""
            close_date = props.get("closed_date") or ""
            
            # Create ADO work item
            ado_pat = os.environ["ADO_PAT"]
            
            # Need to update org and project
            ado_url = (
                "https://dev.azure.com/ftr-test/ScrumDummy/_apis/wit/workitems/$Client%20Issue?api-version=7.0"
            )

            auth_token = base64.b64encode(f":{ado_pat}".encode()).decode()
            ado_headers = {
                "Content-Type": "application/json-patch+json",
                "Authorization": f"Basic {auth_token}"
            }
            logging.info(f"Ticket ID: {ticket_id}\nTitle: {title}\nDescription: {description}\nPriority: {priority}\nClient ID: {client_id}\nResolution Notes: {resolution_notes}")

            # Need to update to include more fields as required
            ado_body = [
                {
                    "op": "add",
                    "path": "/fields/System.Title",
                    "value": title
                },
                {
                    "op": "add",
                    "path": "/fields/System.Description",
                    "value": description
                },
                {
                    "op": "add",
                    "path": "/fields/Custom.ClientPriority",
                    "value": priority
                },
                {
                    "op": "add",
                    "path": "/fields/Custom.Client",
                    "value": client_id
                },
                {
                    "op": "add",
                    "path": "/fields/Custom.Resolutiondetails",
                    "value": resolution_notes
                }
            ]
            
            try:
                ado_response = requests.post(
                    ado_url,
                    headers=ado_headers,
                    data=json.dumps(ado_body)
                )
            except requests.RequestException as e:
                logging.error(f"Error creating ADO work item: {e}")
                return func.HttpResponse("Failed to create ADO work item", status_code=500)

            ado_response.raise_for_status()
            work_item_id = ado_response.json().get("id")

            logging.info(f"ADO Work Item Created: {work_item_id}")

        return func.HttpResponse("OK", status_code=200)

    except Exception as e:
        logging.exception("Webhook processing failed")
        return func.HttpResponse(str(e), status_code=500)
