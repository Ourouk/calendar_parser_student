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
    app.redis_client.set(f"{unique_key}_selectedEventsParsed", json.dumps(selectedEventsParsed))
    app.redis_client.setex(unique_key,expiration_time_for_calendars_in_seconds, generate_ical_file(selectedEventsParsed))
    return render_template('parsed_calendars.html', unique_key=unique_key)


@app.route('/mycal/<key>', methods=["GET"])
def mycal(key):
    if app.redis_client.exists(key):
        # If the key exists in Redis, return the file
        file_data = app.redis_client.get(key)
    else:
        # If the key doesn't exist, generate the file and return it
        selected_events_parsed = json.loads(app.redis_client.get(f"{key}_selectedEventsParsed").decode("utf-8"))
        file_data = generate_ical_file(selected_events_parsed)

    return send_file(BytesIO(file_data), as_attachment=True, download_name="mycal.ics", mimetype='text/calendar')

def fetch_calendars(url):
    exception_domain = "https://horaire-hepl.provincedeliege.be"
    if(app.redis_client.exists(url)):
        ics_text = app.redis_client.get(url).decode("utf-8")
        logging.info(f"Fetched {url} from cache")
        return ics_text
    else:
        response = requests.get(url)
        logging.info(f"Fetched {url}")
        if url.startswith(exception_domain):
            response.encoding = "utf-8"
        decoded_text = response.text
        app.redis_client.setex(url,expiration_time_for_calendars_in_seconds,decoded_text)
        logging.info(f"Fetched {url}")
        return (decoded_text)

def get_recurring_event_names(url):  # We consider that all event that have the same course name are courses
    c = Calendar(fetch_calendars(url))
    events_dic = {}
    events_list = []
    counter = 0
    for e in c.events:
        if e.name not in events_list:
            events_dic[f"e_{counter}"] = e.name
            events_list.append(e.name)
            counter += 1
    return events_dic

def generate_ical_file(selectedEventsParsed):
    parsed_calendars = Calendar()
    for url in selectedEventsParsed:
        temp_calendar = Calendar()
        calendar = Calendar(fetch_calendars(url))
        event_dic = get_recurring_event_names(url)
        event_name_list = []
        for event in selectedEventsParsed[url]:
            event_name_list.append(event_dic.get(event))
        for event in calendar.events:
            if event.name in event_name_list:
                temp_calendar.events.add(event)
        parsed_calendars.events.update(temp_calendar.events)
    return parsed_calendars.serialize()

if __name__ == '__main__':
    app.run(debug=True)