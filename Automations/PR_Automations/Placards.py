"""

Instructions:
  1. Open a terminal at this folder location 
  2. Run the script w/ command below then type out the names 
  3. Script reads Sheet2 of the roster sheet
  4. Removes duplicate rows (double delegates share one placard)
  5. Copies the placard template and fills in {Country_1} and {Country_2}
  6. Puts the deck in the output folder, shares it, and gives us a link

Terminal Command:
cd ~/STMUN/STMUN-Internal-Tools/Automations/PR_Automations 
source ../../venv/bin/activate
python Placards.py
"""

import difflib
import os
import re

""" Google api business, from the google cloud console
Allows the script to access the google slides/sheets and make changes """
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

""" Configs/Constants -> things used throughout the program """

TEMPLATE_ID = "1Ygv6EC7gZT6jHFyvDSxK2dOM-5Z0rpzIBA5GGbkjw2o"      # Placard slides template
SPREADSHEET_ID = "1doJiwSOlgHsoRtPq4XAYqh_m-ogflZNneV2bvMDI8DU"   # Roster sheet

# Sheet2 = the same roster, reorganized by committee
SHEET_RANGE = "Sheet2!A:C"

# Drive folder for finished deck 
OUTPUT_FOLDER_ID = "1amleuLRzSqqqlW1kfXVhtd_hIv17jdmo"

DECK_TITLE_PREFIX = "SCVMUN LVI Placards"   # final title: "<prefix> - <committee>"

ANYONE_WITH_LINK = True      # anyone with the link can view

""" Template layout
The template has one slide with two placards on it. Each placard has the country
on front and back, so {Country_1} and {Country_2} each appear twice.
Two placards per slide, country name twice per placard """

TEMPLATE_SLIDE_INDEX = 0     # pythonic indexing: first slide = 0
PLACARDS_PER_SLIDE = 2

""" Behavior toggles """

SORT_COUNTRIES_WITHIN_COMMITTEE = True   # alphabetical

REQUEST_BATCH_SIZE = 100             # keeps each Slides API call a reasonable size

# Google Permissions the script needs (same as badges -> same token.json works)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",  # reading roster
    "https://www.googleapis.com/auth/presentations",          # editing slides
    "https://www.googleapis.com/auth/drive",                  # copying/sharing
]


"""This function makes sure all of the google credentials are in order """
def get_credentials():
    # token.json is the saved login created the first time you authorize the script
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # refreshes the login if it expired
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)  # opens the browser login
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds


def natural_key(text):
    """Sort alphabetically and numerically for ICJ judges"""
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", text)]


def read_roster(sheets):
    """Return a list of (committee, country) tuples from Sheet2, in sheet order 
    all of the committtees ."""
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE
    ).execute()
    rows = result.get("values", [])

    roster = []
    for row in rows[1:]:  # row 0 is the header
        row = row + [""] * (3 - len(row))  # pad in case a column is empty
        _school, committee, country = (cell.strip() for cell in row[:3])
        if committee and country and committee not in EXCLUDE_COMMITTEES:
            roster.append((committee, country))
    return roster


def group_by_committee(roster):
    """Return {committee: [countries]} => takes the entire roster, and gives us the needed committee """
    groups = {}
    for committee, country in roster:
        groups.setdefault(committee, []).append(country)

    for committee, countries in groups.items():
        if SORT_COUNTRIES_WITHIN_COMMITTEE:
            countries = sorted(countries, key=natural_key)
        groups[committee] = countries
    return groups


def pick_committee(groups, committee_input):
    """Match the typed name """
    wanted = committee_input.strip().lower()

    match = next((c for c in groups if c.lower() == wanted), None) # pythonic langauge, just matching 
    if match is None:
        print(f"\nNo committee named '{committee_input}' found.")
        close = difflib.get_close_matches(committee_input, list(groups), n=5, cutoff=0.4) #AI added its own spell check feature while looking it over (idk)
        print("Did you mean one of these?" if close else "Available committees:")
        for c in (close or groups):
            print(f"  - {c}")
        return None
    return {match: groups[match]}


def make_pages(groups):
    """
    Turn {committee: [countries]} into a list of pages.
    Each page = list of up to 2 (committee, country) pairs.
    """
    pages = []
    """ pythonic functionality, where the groups are flattened 
    # instead of having a bunch of nested lists/groups w/ the committees and countries 
    # this code takes them out, and gives a pages list 
    # this pages list contains 2 committee country pairs, which are then put on the slides """

    flat = [(com, c) for com, cs in groups.items() for c in cs]
    for i in range(0, len(flat), PLACARDS_PER_SLIDE):
        pages.append(flat[i:i + PLACARDS_PER_SLIDE])
    return pages


"""Copy the slide's template in Drive and return the new deck"""
def copy_template(drive, title):
    body = {"name": title}
    if OUTPUT_FOLDER_ID:
        body["parents"] = [OUTPUT_FOLDER_ID]  # puts the copy in the folder
    copy = drive.files().copy(fileId=TEMPLATE_ID, body=body).execute()
    return copy["id"]

""" send_in_batches is API business. 
When we work between the google slides/sheets, we send requests to the API 
Our constant, REQUEST_BATCH_SIZE is 100, 
so we only send 100 requests at a time to make sure nothing crashes 
batchUpdate is the func that sends the request and keeps the batches moving """

def send_in_batches(slides, deck_id, requests):
    for i in range(0, len(requests), REQUEST_BATCH_SIZE):
        slides.presentations().batchUpdate(
            presentationId=deck_id,
            body={"requests": requests[i:i + REQUEST_BATCH_SIZE]},
        ).execute()


"""Fill in the template """
def build_slides(slides, deck_id, pages):
    deck = slides.presentations().get(presentationId=deck_id).execute() # template
    template_slide_id = deck["slides"][TEMPLATE_SLIDE_INDEX]["objectId"]

    """ for the amount of new slides we will need (in the range of length of pages), 
    we need the slide_ids for each so we can accurately match which sldies have been filled
    send_in_batches makes sure these new slides' locations are being properly handled and filled in"""

    new_ids = [f"placard_page_{k}" for k in range(1, len(pages))]
    send_in_batches(slides, deck_id, [
        {"duplicateObject": {"objectId": template_slide_id,
                             "objectIds": {template_slide_id: nid}}}
        for nid in new_ids
    ])

    # Re-read the deck and take the slides in their actual on-screen order
    deck = slides.presentations().get(presentationId=deck_id).execute()
    ours = {template_slide_id, *new_ids}
    slide_ids = [s["objectId"] for s in deck["slides"] if s["objectId"] in ours] 
    # this unpacking allows the slide ids + names to appear in order 
    # really syntactical work ngl

    # Replace {Country_N} on every page (replaceAllText hits front AND back text)
    requests = []
    for slide_id, page in zip(slide_ids, pages): # zip pairs each slide w/ the committee/country pair
        for n in range(1, PLACARDS_PER_SLIDE + 1):
            country = page[n - 1][1] if n <= len(page) else ""  # country[n-1][1] gives proper tuple info 
            requests.append({"replaceAllText": { # replaces necesarry text
                "containsText": {"text": f"{{Country_{n}}}", "matchCase": True},
                "replaceText": country, # only needs to replace country 
                "pageObjectIds": [slide_id],
            }})
    send_in_batches(slides, deck_id, requests) 
    # the request to change the slides is sent in batches 


""" shares the deck"""
def share_deck(drive, deck_id):
    if ANYONE_WITH_LINK:
        drive.permissions().create(
            fileId=deck_id, body={"type": "anyone", "role": "reader"}
        ).execute()

    info = drive.files().get(fileId=deck_id, fields="webViewLink").execute()
    return info["webViewLink"]


""" MAIN """
def main():
    creds = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    slides = build("slides", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    committee_input = input("Which committee do you want placards for: ")

    roster = read_roster(sheets) # get all of the assignments in the sheet in tuple form 
    groups = pick_committee(group_by_committee(roster), committee_input) # group roster by committees, then pick a certain committee 
    if not groups:
        return

    pages = make_pages(groups) # returns 2 commitee/country pairs -> per slide 
    total_placards = sum(len(c) for c in groups.values())
    scope_label = next(iter(groups))

    print(f"\nFound {total_placards} placards across {len(groups)} committee(s) "
          f"-> {len(pages)} slide(s). Building deck...")
    deck_id = copy_template(drive, f"{DECK_TITLE_PREFIX} - {scope_label}")
    build_slides(slides, deck_id, pages)
    link = share_deck(drive, deck_id)

    print(f"\nDone! {len(pages)} slide(s), 2 placards each (country on front and back).")
    print(f"Link: {link}")


if __name__ == "__main__":
    main()
