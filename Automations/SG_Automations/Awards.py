"""
A few notes about the awards generation process:
1. ST delegates are assumed to not be in this list. Chairs should instead text the awards to the Secretariat.
2. A full slide deck is generated with all awards. This is the same slide deck for printing and showing at ceremony.
    - Meaning that double delegation awards are shown twice. Keep this in mind at showing ceremony.
"""

import os

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

def generate_all_awards_by_committee(): # returns a dictionary where keys are (country, committee) tuples and values are award names.
    """
    Fetches all award data from location defined in get_awards and turns it into a Google Slides presentation.
    Placholders are ""
    """
    awards = ServerRequests.get_awards()
    committees_with_awards = awards["committees"]
    names: list[str] = SheetsAPI.get_column_data_until_empty(REGISTRATION_SHEET_ID, "Overview", "A", 2)
    status_booleans = SheetsAPI.read_cells(REGISTRATION_SHEET_ID, [f"Overview!E{i+2}" for i in range(len(names))])
    committee_double_status: dict[str,bool] = {name: status for name, status in zip(names, status_booleans)}

    # Find the amount of awards submitted to determine how many slides to duplicate.
    # Each award is its own slide.
    count = 0
    for committee in committees_with_awards:
        count += len(committee["awards"])
        committee_name = committee["committee"]
        if committee_name in committee_double_status and committee_double_status[committee["committee"]]:
            count += len(committee["awards"]) # double delegation, so double the awards.

    first_slide_ID = Slides.get_first_slide_id(AWARD_SLIDE_ID)
    # duplicate the first slide count-1 times to have enough slides for all awards.
    slide_page_IDs: list[str] = Slides.duplicate_slide_many(AWARD_SLIDE_ID, first_slide_ID, count - 1)
    slide_page_IDs.insert(0, first_slide_ID)

    i = 0
    committee_name_dict: dict[str, str] = {}
    awards_name_dict: dict[str, str] = {}
    assignment_name_dict: dict[str, str] = {}
    for committee in committees_with_awards:
        committee_name = committee["committee"]
        full_committee_name = Display.take_text_input(f"Current Committee Name: {committee_name}. Type out the real name exactly as you want it to appear in the award.")
        for award in committee["awards"]:
            country_name = award["country"]
            award_name = award["award"]
            committee_name_dict[slide_page_IDs[i]] = full_committee_name
            awards_name_dict[slide_page_IDs[i]] = award_name
            assignment_name_dict[slide_page_IDs[i]] = country_name
            i += 1

            if committee_name in committee_double_status and committee_double_status[committee_name]:
                # double delegation, so we need to add the award twice.
                committee_name_dict[slide_page_IDs[i]] = full_committee_name
                awards_name_dict[slide_page_IDs[i]] = award_name
                assignment_name_dict[slide_page_IDs[i]] = country_name
                i += 1

    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{COMMITTEE_NAME}}", committee_name_dict)
    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{AWARD_NAME}}", awards_name_dict)
    Slides.batch_update_slides_text(AWARD_SLIDE_ID, "{{ASSIGNMENT_NAME}}", assignment_name_dict)

"""
Process:
1. Pull all awards from the SCVMUN API.
2. Duplicate amount of slides as necessary.
3. Store all Slide IDs into one central list, which is given by slides functions that duplicate/find first slide ID.
4. Go down the list of awards and for each award, find the corresponding slide ID and place it in a dictionary with desired replacement text of that placeholder.
5. Code keeps in mind ST delegates and double delegation system.
6. Use the batch_update_slides_text function to replace all placeholders with the correct text.
"""
