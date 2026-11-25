"""
badges.py - Build a Google Slides badge deck for ONE school.

Workflow:
  1. You type a school name.
  2. The script reads the roster from the Google Sheet.
  3. It copies the badge template into a new deck (inside a Drive folder).
  4. It fills in {Country_N} / {Committee_N} on each front slide.
  5. It shares the deck and prints the link.

Run:  python badges.py
"""

import difflib
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ----------------------------------------------------------------------
# CONFIG - edit these values
# ----------------------------------------------------------------------

# The long ID in each Google URL:  .../d/<THIS PART>/edit
TEMPLATE_ID = "1HRvv77Ud9K1GsmNzs8-g1OtB7A2112qOkKbO_RHWmoo"      # Slides template
SPREADSHEET_ID = "1doJiwSOlgHsoRtPq4XAYqh_m-ogflZNneV2bvMDI8DU"   # Roster sheet

# Tab name + columns. Columns must be: School, Committee, Country (A, B, C).
SHEET_RANGE = "Sheet1!A:C"   

# Drive folder where finished decks go. Open the folder in Drive and copy the
# Leave as "" to put decks in the top level of My Drive.
OUTPUT_FOLDER_ID = "1U2U7CltjpLoVF0KtIL1nK_9WknKCxZaO"

# Sharing. Add emails to give them edit access, and/or turn on link sharing.
SHARE_WITH_EMAILS = []        # e.g. ["teammate@gmail.com"]
ANYONE_WITH_LINK = True      # True = anyone with the link can VIEW

# Template layout: the template has a FRONT slide (8 badges with placeholders)
# followed by a BACK slide (the schedule). Numbering starts at 0.
FRONT_SLIDE_INDEX = 0
BACK_SLIDE_INDEX = 1

BADGES_PER_SLIDE = 8          # {Country_1} ... {Country_8}

# Permissions the script asks Google for.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",  # read roster
    "https://www.googleapis.com/auth/presentations",          # edit slides
    "https://www.googleapis.com/auth/drive",                  # copy/share files
]


# ----------------------------------------------------------------------
# STEP 1: Log in to Google (OAuth)
# ----------------------------------------------------------------------
def get_credentials():
    """Return valid Google credentials.

    First run: opens a browser so you can click Allow, then saves token.json.
    Later runs: reuses token.json, so no login is needed.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # quietly renew an expired token
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)  # opens the browser login
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds


# ----------------------------------------------------------------------
# STEP 2: Read the roster from Google Sheets
# ----------------------------------------------------------------------
def read_roster(sheets):
    """Return a list of (school, committee, country) tuples from the sheet."""
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE
    ).execute()
    rows = result.get("values", [])

    roster = []
    for row in rows[1:]:  # rows[0] is the header (School, Committee, Country)
        row = row + [""] * (3 - len(row))  # pad short rows so we can unpack
        school, committee, country = (cell.strip() for cell in row[:3])
        if school:
            roster.append((school, committee, country))
    return roster


def delegates_for_school(roster, school_input):
    """Return [(country, committee), ...] for the typed school, or None.

    Matching ignores capitalization and extra spaces. If nothing matches,
    we print the closest school names to help with typos.
    """
    wanted = school_input.strip().lower()

    # Keep each school's real spelling so we can show it later
    all_schools = sorted({s for s, _, _ in roster})
    match = next((s for s in all_schools if s.lower() == wanted), None)

    if match is None:
        print(f"\nNo school named '{school_input}' found.")
        close = difflib.get_close_matches(school_input, all_schools, n=5, cutoff=0.4)
        if close:
            print("Did you mean one of these?")
            for s in close:
                print(f"  - {s}")
        return None, None

    # Duplicate rows are kept on purpose: each delegate needs their own badge.
    delegates = [(country, committee)
                 for s, committee, country in roster if s == match]
    return match, delegates


# ----------------------------------------------------------------------
# STEP 3: Copy the template into a new deck
# ----------------------------------------------------------------------
def copy_template(drive, school):
    """Copy the template in Drive and return the new deck's ID."""
    body = {"name": f"SCVMUN LV Badges - {school}"}
    if OUTPUT_FOLDER_ID:
        body["parents"] = [OUTPUT_FOLDER_ID]  # puts the copy in the folder
    copy = drive.files().copy(fileId=TEMPLATE_ID, body=body).execute()
    return copy["id"]


# ----------------------------------------------------------------------
# STEP 4: Fill in the slides
# ----------------------------------------------------------------------
def build_slides(slides, deck_id, delegates):
    """Make one front+back pair per group of 8 delegates and fill the text.

    Final slide order:  Front1, Back1, Front2, Back2, ...
    so the front and back of each sheet match when printed double-sided.
    """
    # Split delegates into groups of 8 (one group per front slide)
    chunks = [delegates[i:i + BADGES_PER_SLIDE]
              for i in range(0, len(delegates), BADGES_PER_SLIDE)]

    # Look up the object IDs of the template's front and back slides
    deck = slides.presentations().get(presentationId=deck_id).execute()
    front_id = deck["slides"][FRONT_SLIDE_INDEX]["objectId"]
    back_id = deck["slides"][BACK_SLIDE_INDEX]["objectId"]

    # --- 4a. Duplicate the front/back pair for every extra group of 8 ---
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

        # --- 4b. Put slides in Front1, Back1, Front2, Back2... order ---
        # (Duplicates land right after their original, so we re-sort.)
        requests = []
        desired_order = [sid for pair in zip(front_ids, back_ids) for sid in pair]
        for position, sid in enumerate(desired_order):
            requests.append({"updateSlidesPosition": {
                "slideObjectIds": [sid], "insertionIndex": position}})
        slides.presentations().batchUpdate(
            presentationId=deck_id, body={"requests": requests}).execute()

    # --- 4c. Replace the placeholder text on each front slide ---
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
                    # Limit to THIS slide, otherwise every slide's matching
                    # placeholder would be overwritten at once.
                    "pageObjectIds": [slide_id],
                }})
    slides.presentations().batchUpdate(
        presentationId=deck_id, body={"requests": requests}).execute()

    return len(chunks)


# ----------------------------------------------------------------------
# STEP 5: Share the deck
# ----------------------------------------------------------------------
def share_deck(drive, deck_id):
    """Apply sharing settings and return the link to the deck."""
    for email in SHARE_WITH_EMAILS:
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
    return info["webViewLink"]


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
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