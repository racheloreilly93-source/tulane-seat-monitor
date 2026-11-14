
import requests

URL = "https://classschedule.tulane.edu/Search.aspx"

COURSES = {
    "10321": "CHEM 1080-20",
    "39363": "CHEM 1080-30",
    "40834": "CHEM 1085-35",
    "19723": "CHEM 1085-37",
    "56831": "CHEM 1085-38",
}

print("Tulane Seat Monitor")
print("Checking public schedule connectivity...")

try:
    response = requests.get(URL, timeout=20)
    response.raise_for_status()

    print("Website reachable:", response.status_code)
    print("Response length:", len(response.text))
    print("Courses to monitor:")
    for crn, name in COURSES.items():
        print(f"  {crn}: {name}")

except requests.RequestException as error:
    print("Website check failed:", error)
    raise
