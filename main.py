import requests
import redis
from ics import Calendar, Event
from flask import Flask ,render_template,request,send_file
from io import BytesIO
import json
import uuid
import os
import logging

app = Flask(__name__)

# Try loading configuration from environment variables
redis_host = os.environ.get('REDIS_HOST')
redis_port = int(os.environ.get('REDIS_PORT'))
redis_db = int(os.environ.get('REDIS_DB'))
expiration_time_for_calendars_in_seconds = os.environ.get('EXPIRATION_TIME_SECONDS')
app.redis_client = redis.Redis(host=redis_host, port=redis_port, db=redis_db)
logging.basicConfig(level=logging.INFO, format='%(message)s')


@app.route('/')
def index():
    return render_template("index.html")

@app.route('/submited_calendars', methods=['POST'])
def submit():
    urls = request.form.getlist('urls')
    calendars = {}
    for url in urls:
        calendars[url] = get_recurring_event_names(url)
    return render_template('submited_calendars.html', calendars=calendars)

@app.route('/parsed_calendars', methods=['POST'])
def parse_calendars():
    selectedURLEvents = request.form.getlist('selectedEvents')
    selectedEventsParsed = {}
    for event in selectedURLEvents:
        parsed = event.split("#")
        calendar_url = parsed[0]
        event_name = parsed[1]
        # Check if the calendar_url key exists in the dictionary
        if calendar_url in selectedEventsParsed:
            # If it exists, append the event_name to the existing list
            selectedEventsParsed[calendar_url].append(event_name)
        else:
            # If it doesn't exist, create a new list with the event_name as its first element
            selectedEventsParsed[calendar_url] = [event_name]
    unique_key_buff = uuid.uuid5(uuid.NAMESPACE_DNS, str(selectedEventsParsed))
    unique_key = str(unique_key_buff)
    if  not app.redis_client.exists(f"{unique_key}_selectedEventsParsed"):
        app.redis_client.set(f"{unique_key}_selectedEventsParsed", json.dumps(selectedEventsParsed))
    app.redis_client.setex(unique_key,expiration_time_for_calendars_in_seconds, generate_ical_file(selectedEventsParsed,unique_key))
    return render_template('parsed_calendars.html', unique_key=unique_key)


@app.route('/mycal/<key>', methods=["GET"])
def mycal(key):
    # If the key doesn't exist, generate the file and return it
    if app.redis_client.exists(f"{key}_selectedEventsParsed"):
        selected_events_parsed = json.loads(app.redis_client.get(f"{key}_selectedEventsParsed").decode("utf-8"))
    else:
        return "Error"
    file_data = generate_ical_file(selected_events_parsed)
    return send_file(BytesIO(file_data), as_attachment=True, download_name="mycal.ics", mimetype='text/calendar')

def fetch_calendars(url):
    exception_domain = "https://horaire-hepl.provincedeliege.be"
    updated_flag = bool
    decoded_text = str
    if(app.redis_client.exists(url)):
        updated_flag = False
        decoded_text = app.redis_client.get(url).decode("utf-8")
        logging.info(f"Fetched {url} from cache")
    else:
        updated_flag = True
        response = requests.get(url)
        logging.info(f"Fetched {url}")
        if url.startswith(exception_domain):
            response.encoding = "utf-8"
        decoded_text = response.text
        app.redis_client.setex(url,expiration_time_for_calendars_in_seconds,decoded_text)
    return decoded_text,updated_flag

def get_recurring_event_names(url):  # We consider that all event that have the same course name are courses
    ics_text,update_flag=fetch_calendars(url)
    c = Calendar(ics_text)
    events_dic = {}
    events_list = []
    counter = 0
    for e in c.events:
        if e.name not in events_list:
            events_dic[f"e_{counter}"] = e.name
            events_list.append(e.name)
            counter += 1
    return events_dic

def generate_ical_file(selectedEventsParsed,unique_key):
    parsed_calendars = Calendar()
    update_flags = []
    ics_texts = []
    for url in selectedEventsParsed:
        temp_calendar = Calendar()
        ics_text,update_flag=fetch_calendars(url)
        update_flags.append(update_flag)
        ics_texts.append(ics_text)
    if(any(update_flags) or not app.redis_client.exists(unique_key)):
        for ics_text in ics_texts:
            calendar = Calendar(ics_text)
            event_dic = get_recurring_event_names(url)
            event_name_list = []
            for event in selectedEventsParsed[url]:
                event_name_list.append(event_dic.get(event))
            for event in calendar.events:
                if event.name in event_name_list:
                    temp_calendar.events.add(event)
            parsed_calendars.events.update(temp_calendar.events)
        logging.info(f"Fetched {unique_key} from cache")
        ics_text = parsed_calendars.serialize()
        app.redis_client.setex(unique_key,expiration_time_for_calendars_in_seconds * 2,ics_text)
    else:
        logging.info(f"Fetched {unique_key} from cache")
        ics_text = app.redis_client.get(unique_key).decode("utf-8")
    return ics_text

if __name__ == '__main__':
    app.run(debug=True)