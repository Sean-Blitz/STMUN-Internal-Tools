"""
Instructions on how to get the automation working 
  1. Open a terminal at this folder location on your local device (will only work on Sahaj's personal computer right now)
  2. Type a school name.
  3. Script will read the google sheet w/ all the schools and assignments
  4. Copies the info onto the badge template 
  5. Fills in {Country_N} and {Committee_N} 
  6. Puts the deck in folder, and gives us a link

Terminal Command: 
cd ~/STMUN-placard-badge/STMUN-Internal-Tools/Automations/PR_Automations
source ../../venv/bin/activate
python Badges.py
"""

import difflib
import os

""" Google api business, from the google cloud console 
Allows the script to access the google slides/sheets and make changes """
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

""" Configs/Constants -> things used throughout the program"""

TEMPLATE_ID = "1HRvv77Ud9K1GsmNzs8-g1OtB7A2112qOkKbO_RHWmoo"      # Slides template
SPREADSHEET_ID = "1doJiwSOlgHsoRtPq4XAYqh_m-ogflZNneV2bvMDI8DU"   # Roster sheet

SHEET_RANGE = "Sheet1!A:C"   

OUTPUT_FOLDER_ID = "1U2U7CltjpLoVF0KtIL1nK_9WknKCxZaO"


SHARE_WITH_EMAILS = []        # claude function it added 
ANYONE_WITH_LINK = True      # anyone with the link can access

""" Slide template uses pythonic indexing 
The front of the badge is at 0, and the back side is at 1"""
FRONT_SLIDE_INDEX = 0
BACK_SLIDE_INDEX = 1

BADGES_PER_SLIDE = 8          # Constant for there being 8 badges per slide 

# Google Permissions the script needs
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",  # reading roster
    "https://www.googleapis.com/auth/presentations",          # editing slides
    "https://www.googleapis.com/auth/drive",                  # copying/sharing
]


"""This function makes sure all of the google credentials are in order """

def get_credentials():
    
    # token.json is the credentials given by the google cloud console 
    # for the script to be able to access the slides/sheets 
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  
            # google api function that troubleshoots in case the credentials stop working 
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)  # opens the browser login
        with open("token.json", "w") as f: # opens the creds as a file, and then stores it
            f.write(creds.to_json())
    return creds


# reads the google sheet contianing all schools/assignments 
def read_roster(sheets):
    """Return a list of (school, committee, country) tuples from the sheet."""
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE
    ).execute()
    rows = result.get("values", [])


    roster = []
    for row in rows[1:]:  # starts at 1, since row 0 is the header
        row = row + [""] * (3 - len(row)) # adds empty strings in case a column is empty 
        school, committee, country = (cell.strip() for cell in row[:3]) # unpacks values, strips whitespace
        if school: # if school contains text (safety) then append the values to the roster
            roster.append((school, committee, country))
    return roster


def delegates_for_school(roster, school_input):
    """
    When we input the school in the terminal -> the function
    checks for the corresponding country/committee for each delegate that goes to a school
    """
    wanted = school_input.strip().lower() # school input is what's in the terminal

    all_schools = sorted({s for s, _, _ in roster})
    match = next((s for s in all_schools if s.lower() == wanted), None) 
    # spelling checks 

    if match is None: # if no school matches the name, then
        print(f"\nNo school named '{school_input}' found.")
        close = difflib.get_close_matches(school_input, all_schools, n=5, cutoff=0.4) # some spelling check function lol
        if close:
            print("Did you mean one of these?")
            for s in close:
                print(f"  - {s}")
        return None, None

    # Duplicate rows are kept for double dels 
    delegates = [(country, committee)
                 for s, committee, country in roster if s == match]
    return match, delegates


"""Copy the slide's template in Drive and return the new deck"""
def copy_template(drive, school):
    body = {"name": f"SCVMUN LV Badges - {school}"} # set the title of the slide to the school's name 
    if OUTPUT_FOLDER_ID:
        body["parents"] = [OUTPUT_FOLDER_ID]  # puts the copy in the folder
    copy = drive.files().copy(fileId=TEMPLATE_ID, body=body).execute()
    return copy["id"]


"""Fill in the template """
def build_slides(slides, deck_id, delegates):

    # Chunks delegates into groups of 8 (one group per front slide)
    # BADGES_PER_SLIDE = 8 
    chunks = [delegates[i:i + BADGES_PER_SLIDE]
              for i in range(0, len(delegates), BADGES_PER_SLIDE)]

    # Function needs the object IDs of the template's front and back slides
    # This is so it can copy these front/back slides, if there are more than 8 dels
    deck = slides.presentations().get(presentationId=deck_id).execute()
    front_id = deck["slides"][FRONT_SLIDE_INDEX]["objectId"]
    back_id = deck["slides"][BACK_SLIDE_INDEX]["objectId"]

    # Duplicate the front/back pair for every extra group of 8 
    # We choose the new slide IDs ourselves so we can find them afterwards.
    front_ids = [front_id]
    back_ids = [back_id]
    requests = []
    for k in range(1, len(chunks)):
        new_front, new_back = f"front_{k}", f"back_{k}"
        requests.append({"duplicateObject": {
            "objectId": front_id, "objectIds": {front_id: new_front}}})
        requests.append({"duplicateObject": {
            "objectId": back_id, "objectIds": {back_id: new_back}}})
        front_ids.append(new_front)
        back_ids.append(new_back)
    if requests:
        slides.presentations().batchUpdate(
            presentationId=deck_id, body={"requests": requests}).execute()

        # Put slides in Front1, Back1, Front2, Back2... order 
        # Claude resorted it, so Duplicates land right after their original
        requests = []
        desired_order = [sid for pair in zip(front_ids, back_ids) for sid in pair]
        for position, sid in enumerate(desired_order):
            requests.append({"updateSlidesPosition": {
                "slideObjectIds": [sid], "insertionIndex": position}})
        slides.presentations().batchUpdate(
            presentationId=deck_id, body={"requests": requests}).execute()

    # Replace the placeholder text on each front slide ---
    requests = []
    for slide_id, chunk in zip(front_ids, chunks):
        for n in range(1, BADGES_PER_SLIDE + 1):
            if n <= len(chunk):
                country, committee = chunk[n - 1]
            else:
                country, committee = "", ""  # unused slot -> blank badge

            for placeholder, value in (
                (f"{{Country_{n}}}", country),
                (f"{{Committee_{n}}}", committee),
            ):
                requests.append({"replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": value,
                    "pageObjectIds": [slide_id],
                }})
    slides.presentations().batchUpdate(
        presentationId=deck_id, body={"requests": requests}).execute()

    return len(chunks) # returns length of how many slide pages 


""" shares the deck"""
def share_deck(drive, deck_id):
    """Apply sharing settings and return the link to the deck."""
    for email in SHARE_WITH_EMAILS: # extra claude function, if we only needed specific emails
        drive.permissions().create(
            fileId=deck_id,
            body={"type": "user", "role": "writer", "emailAddress": email},
            sendNotificationEmail=False,
        ).execute()

    if ANYONE_WITH_LINK:
        drive.permissions().create(
            fileId=deck_id, body={"type": "anyone", "role": "reader"}
        ).execute()

    info = drive.files().get(fileId=deck_id, fields="webViewLink").execute()
    return info["webViewLink"] # returns the link


""" MAIN """
def main():
    creds = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    slides = build("slides", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    school_input = input("Which school do you want badges for? ")

    roster = read_roster(sheets)
    school, delegates = delegates_for_school(roster, school_input)
    if not delegates:
        return

    print(f"\nFound {len(delegates)} delegates for {school}. Building deck...")
    deck_id = copy_template(drive, school)
    num_pages = build_slides(slides, deck_id, delegates)
    link = share_deck(drive, deck_id)

    print(f"Done! {num_pages} badge page(s) (each with a back side).")
    print(f"Link: {link}")


if __name__ == "__main__":
    main()
