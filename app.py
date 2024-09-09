from flask import Flask, request, jsonify, render_template, redirect, session
import firebase_admin, pyrebase, requests
from firebase_admin import credentials, db
import datetime, time, threading
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
cred = credentials.Certificate("./Admin-console.json")
firebase_admin.initialize_app(cred, { 'databaseURL': 'https://marketing-data-d141d-default-rtdb.firebaseio.com/'})
config = {"apiKey": "AIzaSyCMp8OJqHy8CkWr6AfYZ0DMMi40wKI98VM",  "authDomain": "marketing-data-d141d.firebaseapp.com",  "databaseURL": "https://marketing-data-d141d-default-rtdb.firebaseio.com",  "projectId": "marketing-data-d141d",  "storageBucket": "marketing-data-d141d.appspot.com",  "messagingSenderId": "566962550940",  "appId": "1:566962550940:web:eee189eca2bb49309e5559",  "measurementId": "G-Z54PR6Y2ZP"}
firebase = pyrebase.initialize_app(config)
auth_pb = firebase.auth()
app.secret_key = 'AIzaSyCMp8OJqHy8CkWr6AfYZ0DMMi40wKI98VM'

def get_name_by_uid(uid):
    staff_ref = db.reference('staff')
    staff_details = staff_ref.child(uid).get()
    if staff_details:
        return staff_details.get('name', '')
    else:
        return ''

@app.route('/', methods=['POST', 'GET'])
def home():
    return redirect('/login')

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            return jsonify({"status": "error", "message": "Email and password are required"})

        try:
            user = auth_pb.sign_in_with_email_and_password(email, password)
            user_id = user['localId']
            session['uid'] = user_id

            return jsonify({"status": "success", "user_id": user_id})
           
        except Exception as e:
            error_message = str(e)
            if "EMAIL_NOT_FOUND" in error_message:
                return jsonify({"status": "error", "message": "Email not found"})
            elif "INVALID_PASSWORD" in error_message:
                return jsonify({"status": "error", "message": "Incorrect password"})
            else:
                return jsonify({"status": "error", "message": "Authentication failed: " + error_message})
        
    return render_template('login.html')

@app.route('/home', methods=['GET'])
def customer_home():
    customer_ref = db.reference('customer')
    customers = []
    feedbacks = []

    for phone_number, details in customer_ref.get().items():
        if details.get('LeadIncharge') == 'Not Assigned':
            customers.append({"phone_number": phone_number, "details": details})

        if details.get('tc_feedback') and details['tc_feedback'] != "Excellent!":
            feedbacks.append({"phone_number": phone_number, "name": details.get('name', 'N/A'),
                              "lead_incharge": details.get('LeadIncharge', 'N/A'),
                              "feedback_type": "TC Feedback",
                              "feedback": details.get('tc_feedback')})
        if details.get('pr_feedback') and details['pr_feedback'] != "Excellent!":
            feedbacks.append({"phone_number": phone_number, "name": details.get('name', 'N/A'),
                              "lead_incharge": details.get('LeadIncharge', 'N/A'),
                              "feedback_type": "PR Feedback",
                              "feedback": details.get('pr_feedback')})
        if details.get('installation_feedback') and details['installation_feedback'] != "Excellent!":
            feedbacks.append({"phone_number": phone_number, "name": details.get('name', 'N/A'),
                              "lead_incharge": details.get('LeadIncharge', 'N/A'),
                              "feedback_type": "Installation Feedback",
                              "feedback": details.get('installation_feedback')})

    now = datetime.datetime.now()
    current_year = now.year
    current_month = f"{now.month:02d}"
    current_day = f"{now.day:02d}"

    attendance_ref_path = f'attendance/{current_year}/{current_month}/{current_day}'
    attendance_ref = db.reference(attendance_ref_path)

    attendance_data = attendance_ref.get()
    if (attendance_data):
        allowed_uids = set(attendance_data.keys())
    else:
        allowed_uids = set()

    staff_ref = db.reference('staff')
    tc_staff = []
    for uid, staff_details in staff_ref.get().items():
        if staff_details.get('designation') == 'Telecaller' and uid in allowed_uids:
            tc_staff.append({"name": staff_details['name'], "uid": uid, "mobile": staff_details['work_phoneNumber']})

    leads_ref = db.reference('leads')
    Leads = leads_ref.get()
    total_customers = len(Leads) if Leads else 0

    return render_template('home.html', customers=customers, tc_staff=tc_staff, total_customers=total_customers, leads=Leads, feedbacks=feedbacks)


@app.route('/wati_webhook', methods=['POST'])
def wati_webhook():
    data = request.json
    wa_id = data.get('waId')
    text = data.get('text')

    valid_feedbacks = {"Excellent!", "Average", "Need Improvements"}

    if wa_id and text and text in valid_feedbacks:
        last_10_digits = wa_id[-10:]
        customers_ref = db.reference('customer').get()
        customer_found = False
        for key, value in customers_ref.items():
            if key.endswith(last_10_digits):
                customer_found = True
                ref = db.reference(f'customer/{key}')
                updates = {}

                if 'tc_feedback' in value:
                    if 'pr_feedback' in value:
                        updates['installation_feedback'] = text
                    else:
                        updates['pr_feedback'] = text
                else:
                    updates['tc_feedback'] = text

                ref.update(updates)
                break

        if customer_found:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "error", "message": "Customer not found"}), 404
    else:
        return jsonify({"status": "error", "message": "Invalid data or feedback text"}), 400



@app.route('/upload_excel', methods=['POST'])
def upload_excel():
    from datetime import datetime
    import time
    data = request.get_json()

    def send_whatsapp_messages(url, message, headers):
        response = requests.post(url, json=message, headers=headers)
        return response

    def send_messages_for_lead(lead_data):
        phone_number = str(lead_data.get('phone_number'))
        customer_name = lead_data.get('fullName')
        platform = lead_data.get('platform')
        current_date = datetime.now()
        formatted_date = current_date.strftime('%Y-%m-%d')

        if not phone_number:
            return {"error": "Missing or empty phone number", "lead_data": lead_data}
        if phone_number.startswith('p:'):
            phone_number = phone_number[2:]
        try:
            lead_data_to_store = {
                'name': lead_data.get('fullName'),
                'phone_number': phone_number,
                'city': lead_data.get('city'),
                'campaign_name': lead_data.get('campaign_name'),
                'platform': platform,
                'gate_type': lead_data.get('gate_type'),
                'work_phone_number': lead_data.get('work_phone_number'),
                'created_date': formatted_date
            }

            ref.child(phone_number).set(lead_data_to_store)

            headers = {
                'Content-Type': 'application/json-patch+json',
                'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI5YTZhMTZhYS1mNmRjLTQ1Y2QtYTQzOS00ODQ1YjVjYjRjMmQiLCJ1bmlxdWVfbmFtZSI6Im5hdmluQG9ud29yZHMuaW4iLCJuYW1laWQiOiJuYXZpbkBvbndvcmRzLmluIiwiZW1haWwiOiJuYXZpbkBvbndvcmRzLmluIiwiYXV0aF90aW1lIjoiMDUvMjgvMjAyNCAxMjoxMTo0OCIsImRiX25hbWUiOiJtdC1wcm9kLVRlbmFudHMiLCJ0ZW5hbnRfaWQiOiIxMTYxOTEiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOiJBRE1JTklTVFJBVE9SIiwiZXhwIjoyNTM0MDIzMDA4MDAsImlzcyI6IkNsYXJlX0FJIiwiYXVkIjoiQ2xhcmVfQUkifQ.abMlOvYwJEIZuITmjCTCddMFSkGzi8aPuO_cak6DqaI'
            }

            # Send welcome message
            welcome_message_url = f"https://live-mt-server.wati.io/116191/api/v1/sendTemplateMessage?whatsappNumber={phone_number}"
            welcome_message = {
                "template_name": "greeting_messages",
                "broadcast_name": "greeting_messages",
                "parameters": [
                    {"name": "customer_name", "value": customer_name}, 
                    {"name": "platform", "value": platform}
                ]
            }
            send_whatsapp_messages(welcome_message_url, welcome_message, headers)

            time.sleep(30)

            # Send video messages
            videos = [
                {
                    "template_name": "swing_gatevideo",
                    "broadcast_name": "swing_gatevideo",
                    "parameters": [{"name": "swing_gatevideo", "value": "swing_gatevideo"}]
                },
                {
                    "template_name": "sliding_gatevideo",
                    "broadcast_name": "sliding_gatevideo",
                    "parameters": [{"name": "sliding_gatevideo", "value": "sliding_gatevideo"}]
                },
                {
                    "template_name": "swing_gate_rollermotor_video",
                    "broadcast_name": "swing_gate_rollermotor_video",
                    "parameters": [{"name": "swing_gate_rollermotor_video", "value": "swinggate_rollermotor_video"}]
                }
            ]

            for index, video in enumerate(videos):
                video_url = f"https://live-server-116191.wati.io/api/v2/sendTemplateMessage?whatsappNumber={phone_number}"
                send_whatsapp_messages(video_url, video, headers)

                if index < len(videos) - 1:
                    time.sleep(5)

        except Exception as e:
            return {"phone_number": phone_number, "error": str(e)}

        return None

    if isinstance(data, list):
        errors = []
        ref = db.reference('leads')

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(send_messages_for_lead, lead_data) for lead_data in data]
            for future in futures:
                error = future.result()
                if error:
                    errors.append(error)

        if errors:
            return jsonify({"status": "partial success", "errors": errors}), 207
        return jsonify({"status": "success"}), 200
    else:
        return jsonify({"error": "Expected an array of objects"}), 400


@app.route('/upload_leads', methods=['POST'])
def upload_leads():
    user_id = session.get('uid')

    data = request.get_json()
    LeadIncharge = data.get('selectedUser')
    selected_leads = data.get('selectedLeads')
    LeadInchargeMobile = data.get('selectedMobile') 
    Requirement = data.get('requirement')
     
    ref = db.reference('customer')
    ref1 = db.reference('new_customers')
    leads_ref = db.reference('leads')
  
    for lead in selected_leads:
        full_name = lead.get('name')
        created_date = lead.get('created_date')
        customer_phone_number = lead.get('phone_number')
        lead['created_by'] = get_name_by_uid(user_id)
        lead['LeadIncharge'] = LeadIncharge
        lead['name'] = full_name
        lead['created_date'] = created_date
        lead['customer_state'] = "New leads"
        lead['inquired_for'] = Requirement
        if not customer_phone_number or not full_name:
            return jsonify({'status': 'error', 'message': 'Each lead must have phone_number and full_name'}), 400
        
        if customer_phone_number.startswith('p:'):
                    customer_phone_number = customer_phone_number[2:]
        try:
            ref.child(customer_phone_number).set(lead)
            ref1.child(customer_phone_number).set(lead)
            delete_lead = leads_ref.child(customer_phone_number)
            delete_lead.delete()
            
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Failed to store lead: {str(e)}'}), 500
        
        url = f"https://live-mt-server.wati.io/116191/api/v1/sendTemplateMessage?whatsappNumber={customer_phone_number}"
    
        data = {
            "template_name": "telecaller_assign",
            "broadcast_name": "telecaller_assign",
            "parameters": [
                {"name": "customer_name", "value": full_name},
                {"name": "telecaller_name", "value": LeadIncharge},
                {"name": "phone_number", "value": LeadInchargeMobile}
            ]
        }
        
        headers = {
            'Content-Type': 'application/json-patch+json',
            'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI5YTZhMTZhYS1mNmRjLTQ1Y2QtYTQzOS00ODQ1YjVjYjRjMmQiLCJ1bmlxdWVfbmFtZSI6Im5hdmluQG9ud29yZHMuaW4iLCJuYW1laWQiOiJuYXZpbkBvbndvcmRzLmluIiwiZW1haWwiOiJuYXZpbkBvbndvcmRzLmluIiwiYXV0aF90aW1lIjoiMDUvMjgvMjAyNCAxMjoxMTo0OCIsImRiX25hbWUiOiJtdC1wcm9kLVRlbmFudHMiLCJ0ZW5hbnRfaWQiOiIxMTYxOTEiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOiJBRE1JTklTVFJBVE9SIiwiZXhwIjoyNTM0MDIzMDA4MDAsImlzcyI6IkNsYXJlX0FJIiwiYXVkIjoiQ2xhcmVfQUkifQ.abMlOvYwJEIZuITmjCTCddMFSkGzi8aPuO_cak6DqaI'
        }
        
        try:    
            response = requests.post(url, json=data, headers=headers)
            response.raise_for_status() 
        except requests.exceptions.RequestException as e:
            return jsonify({'status': 'error', 'message': f'Failed to send WhatsApp message: {str(e)}'}), 500
    
    return jsonify({'status': 'success', 'message': 'Leads stored successfully'}), 200


def send_whatsapp_message(url, data, headers):
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f'Failed to send WhatsApp message: {str(e)}')
        
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)