import requests, time, threading

URL = "http://127.0.0.1:5000/incidents"
payload = {
  "user":"stress",
  "description":"network down",
  "type":"red",
  "severity":3
}

def send():
  try:
    r = requests.post(URL, json=payload, timeout=1)
    print(r.status_code)
  except:
    print("ERR")

for _ in range(50):
  threading.Thread(target=send).start()
  time.sleep(0.005)  # <10ms para forzar violaciones
