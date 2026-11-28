"""
A few notes about the awards generation process:
1. ST delegates are assumed to not be in this list. Chairs should instead text the awards to the Secretariat.
2. A full slide deck is generated with all awards. This is the same slide deck for printing and showing at ceremony.
    - Meaning that double delegation awards are shown twice. Keep this in mind at showing ceremony.
"""

import os
from collections import Counter

from dotenv import load_dotenv; load_dotenv()
from Infrastructure import DisplayClass
from Infrastructure import SheetAPI
from SG_Automations import ServerRequests
from Infrastructure import SlideAPI
SheetsAPI = SheetAPI()
Display = DisplayClass()
Slides = SlideAPI()

REGISTRATION_SHEET_ID = os.environ["REGISTRATION_SHEET_ID"]
AWARD_SLIDE_ID = os.environ["AWARD_SLIDE_ID"]

def _require_awards_env():
    missing = [
        name for name, value in (
            ("registration_sheet_ID", REGISTRATION_SHEET_ID),
            ("AWARD_SLIDE_ID", AWARD_SLIDE_ID),
        ) if not value
    ]
    if missing:
        raise RuntimeError("Missing environment variable(s): " + ", ".join(missing))

def _as_bool(value) -> bool:
    """Normalizes a Sheets checkbox / TRUE-FALSE cell to a bool."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1"}

def _normalize(name: str) -> str:
    return name.strip().lower()

def generate_all_awards_by_committee(committees_with_awards = None):
    """
    Fetches all award data from the SCVMUN API, duplicates the award slide for every
    award (twice for double-delegation committees), and fills each slide's
    COMMITTEE_NAME / AWARD_NAME / COUNTRY_NAME placeholders.
    """
    _require_awards_env()
    if committees_with_awards is None:
        # Format: [{"committee": "Committee Name", "awards": [{"country": "Country Name", "award": "Award Name"}, ...]}, ...]
        committees_with_awards = ServerRequests.get_awards()
    names: list[str] = SheetsAPI.get_column_data_until_empty(REGISTRATION_SHEET_ID, "Overview", "A", 2)
    status_booleans = SheetsAPI.read_cells(REGISTRATION_SHEET_ID, [f"Overview!E{i+2}" for i in range(len(names))])
    committee_double_status: dict[str, bool] = {
        _normalize(name): _as_bool(status) for name, status in zip(names, status_booleans)
    }

    # Each award gets its own slide; double-delegation committees show each award twice.
    count = 0
    for committee in committees_with_awards:
        award_count = len(committee.get("awards") or [])
        count += award_count
        if committee_double_status.get(_normalize(committee["committee"]), False):
            count += award_count

    if count == 0:
        Display.display("No awards found. Nothing to generate.")
        return

    first_slide_ID = Slides.get_first_slide_id(AWARD_SLIDE_ID)
    # duplicate the first slide count-1 times to have enough slides for all awards.
    slide_page_IDs: list[str] = Slides.duplicate_slide_many(AWARD_SLIDE_ID, first_slide_ID, count - 1)
    slide_page_IDs.insert(0, first_slide_ID)
    if len(slide_page_IDs) != count:
        raise RuntimeError(f"Expected {count} award slides but got {len(slide_page_IDs)}.")

    i = 0
    committee_name_dict: dict[str, str] = {}
    awards_name_dict: dict[str, str] = {}
    country_name_dict: dict[str, str] = {}
    for committee in committees_with_awards:
        committee_name = committee["committee"]
        awards_list = committee.get("awards") or []
        if not awards_list:
            continue

        full_committee_name = Display.take_text_input(
            f"Current Committee Name: {committee_name}. Type out the real name exactly as you want it to appear in the award."
        )
        is_double = committee_double_status.get(_normalize(committee_name), False)

        for award in awards_list:
            country_name = award["country"]
            award_name = award["award"]
            committee_name_dict[slide_page_IDs[i]] = full_committee_name
            awards_name_dict[slide_page_IDs[i]] = award_name
            country_name_dict[slide_page_IDs[i]] = country_name
            i += 1

            if is_double:
                # double delegation, so we need to add the award twice.
                committee_name_dict[slide_page_IDs[i]] = full_committee_name
                awards_name_dict[slide_page_IDs[i]] = award_name
                country_name_dict[slide_page_IDs[i]] = country_name
                i += 1

    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{COMMITTEE_NAME}}", committee_name_dict)
    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{AWARD_NAME}}", awards_name_dict)
    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{COUNTRY_NAME}}", country_name_dict)

"""
Process:
1. Pull all awards from the SCVMUN API.
2. Duplicate amount of slides as necessary.
3. Store all Slide IDs into one central list, which is given by slides functions that duplicate/find first slide ID.
4. Go down the list of awards and for each award, find the corresponding slide ID and place it in a dictionary with desired replacement text of that placeholder.
5. Code keeps in mind ST delegates and double delegation system.
6. Use the batch_update_slides_text function to replace all placeholders with the correct text.
"""

def view_committee_award_submission_status():
    """
    Fetches all award data and prints, for each committee, how many awards of each
    type were submitted, plus the committees that submitted no awards.

    Counts reflect the awards submitted through the API; double-delegation committees
    are not doubled here (the doubling only applies to the generated slide deck).
    """
    _require_awards_env()
    committees_with_awards = ServerRequests.get_awards()
    names: list[str] = SheetsAPI.get_column_data_until_empty(REGISTRATION_SHEET_ID, "Overview", "A", 2)

    # Overview order is the canonical committee list; API-only committees are appended.
    display_names: dict[str, str] = {_normalize(name): name for name in names}
    counts_by_committee: dict[str, Counter] = {}

    for committee in committees_with_awards:
        committee_name = committee["committee"]
        key = _normalize(committee_name)
        display_names.setdefault(key, committee_name)
        counts = counts_by_committee.setdefault(key, Counter())
        for award in committee.get("awards") or []:
            counts[award["award"]] += 1

    Display.display("Committee Award Submission Status:")
    committees_without_awards = []
    for key, display_name in display_names.items():
        counts = counts_by_committee.get(key)
        if not counts:
            committees_without_awards.append(display_name)
            continue

        total = sum(counts.values())
        breakdown = ", ".join(
            f"{award}: {count}"
            for award, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )
        Display.display(f"{display_name}: {total} award(s) - {breakdown}")

    if committees_without_awards:
        Display.display("")
        Display.display("Committees without awards: " + ", ".join(committees_without_awards))
    else:
        Display.display("All committees have submitted awards.")
