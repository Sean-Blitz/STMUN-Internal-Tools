"""Generate a print-ready badge deck from Airtable assignments.

Each delegate gets one badge front (country + committee). Badges are grouped by
school so a school's badges stay together, and the schedule slide from the
template is copied onto the back of every printed sheet.

Setup (once, in Automations/Infrastructure/Airtable/.env):
    API_KEY                        Airtable personal access token
    AirtableBaseID                 base holding the delegate table
    AirtableTableName              table with one row per delegate

Dependencies (once, from the repository root):
    python3 -m pip install --target .deps -r Automations/PR_Automations/requirements.txt

    Installed into .deps rather than a venv because `python -m venv` refuses to
    build an environment whose path contains ':' (this checkout's folder name
    does), and PYTHONPATH cannot express such a path either - it is the same
    separator. The bootstrap below adds .deps to sys.path in-process instead.

The template deck is expected to hold two slides: slide 1 is a badge front with
slots {Country_1}/{Committee_1} ... {Country_8}/{Committee_8}, and slide 2 is
the schedule that gets copied onto the back of every sheet. Marker text must
match exactly, because replacements are case-sensitive.

Run from the repository root:
    python -m Automations.PR_Automations.Badges --dry-run   # report only
    python -m Automations.PR_Automations.Badges             # build the deck
"""

import os
import sys
from dataclasses import dataclass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# Project-local dependencies (see "Dependencies" above). Harmless when the
# folder is absent, e.g. once the checkout lives under a colon-free path and a
# normal venv or site-packages install is used.
DEPS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".deps"))
if os.path.isdir(DEPS_DIR) and DEPS_DIR not in sys.path:
    sys.path.insert(0, DEPS_DIR)

from ..Infrastructure import AirtableAPI, DisplayClass, DriveAPI, SlideAPI

Display = DisplayClass()

# ---------------------------------- Settings ----------------------------------
TEMPLATE_DECK_ID = "1HRvv77Ud9K1GsmNzs8-g1OtB7A2112qOkKbO_RHWmoo"
OUTPUT_DECK_NAME = "SCVMUN 2027 Badges"
BADGES_PER_SLIDE = 8
BACK_SLIDE_INDEX = 1

BASE_ID = os.getenv("AirtableBaseID")
DELEGATES_TABLE = os.getenv("AirtableTableName")

# All four are plain text fields on the delegates table.
SCHOOL_FIELD = "School Name"
COUNTRY_FIELD = "Country"
COMMITTEE_FIELD = "Committee Assigned"
DELEGATE_NUMBER_FIELD = "Delegate #"


@dataclass(frozen=True)
class Badge:
    school: str
    country: str
    committee: str
    delegate_number: str


def _text(value):
    """Airtable hands back str/int/None; normalise to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def _delegate_sort_key(number):
    """Order delegates 1, 2, 10 rather than 1, 10, 2; odd values go last."""
    try:
        return (0, int(number))
    except (TypeError, ValueError):
        return (1, _text(number))


def load_badges(airtable):
    """Returns (badges, problems) built from every delegate row in Airtable."""
    badges = []
    problems = []

    for record in airtable.get_all_records(BASE_ID, DELEGATES_TABLE):
        fields = record.get("fields", {})
        school = _text(fields.get(SCHOOL_FIELD))
        country = _text(fields.get(COUNTRY_FIELD))
        committee = _text(fields.get(COMMITTEE_FIELD))
        number = _text(fields.get(DELEGATE_NUMBER_FIELD))

        missing = [
            label
            for label, value in (
                ("school", school),
                ("country", country),
                ("committee", committee),
            )
            if not value
        ]
        if missing:
            problems.append(
                f"{school or '(no school)'} #{number or '?'} - missing {' and '.join(missing)}"
            )
            continue

        badges.append(Badge(school, country, committee, number))

    return badges, problems


def group_by_school(badges):
    """{school: [badges...]}, schools alphabetical, delegates in number order."""
    grouped = {}
    for badge in badges:
        grouped.setdefault(badge.school, []).append(badge)

    return {
        school: sorted(
            grouped[school], key=lambda badge: _delegate_sort_key(badge.delegate_number)
        )
        for school in sorted(grouped, key=str.casefold)
    }


def split_into_sheets(badges_by_school):
    """Flattens the school groups into chunks of BADGES_PER_SLIDE."""
    ordered = [
        badge
        for school_badges in badges_by_school.values()
        for badge in school_badges
    ]
    return [
        ordered[index:index + BADGES_PER_SLIDE]
        for index in range(0, len(ordered), BADGES_PER_SLIDE)
    ]


def report(badges_by_school, sheets):
    total = sum(len(school_badges) for school_badges in badges_by_school.values())
    Display.display("")
    Display.display(f"{total} badges from {len(badges_by_school)} schools")
    Display.display(
        f"{len(sheets)} sheets to print ({len(sheets)} fronts + {len(sheets)} schedule backs)"
    )
    Display.display("")
    for school, school_badges in badges_by_school.items():
        Display.display(f"  {school}: {len(school_badges)}")


def fill_sheet(slides, deck_id, slide_id, sheet):
    """Writes up to 8 badges into one slide, blanking unused slots."""
    value_map = {}
    for slot in range(1, BADGES_PER_SLIDE + 1):
        badge = sheet[slot - 1] if slot <= len(sheet) else None
        value_map[f"{{Country_{slot}}}"] = badge.country if badge else ""
        value_map[f"{{Committee_{slot}}}"] = badge.committee if badge else ""

    slides.replace_placeholders_on_slide(deck_id, slide_id, value_map)


def build_deck(sheets):
    drive = DriveAPI()
    slides = SlideAPI()

    deck_id = drive.copy_drive_file(TEMPLATE_DECK_ID, new_name=OUTPUT_DECK_NAME)

    front_template = slides.get_first_slide_id(deck_id)
    back_template = slides.get_slide_id_by_index(deck_id, BACK_SLIDE_INDEX)

    Display.display(f"Filling {len(sheets)} front slides...")
    front_ids = slides.duplicate_slide_many(deck_id, front_template, len(sheets))
    if len(front_ids) != len(sheets):
        sys.exit(
            f"Slides returned {len(front_ids)} copies for {len(sheets)} sheets; "
            "aborting before the deck is half-filled."
        )

    for slide_id, sheet in zip(front_ids, sheets):
        fill_sheet(slides, deck_id, slide_id, sheet)

    Display.display("Copying the schedule onto the back of each sheet...")
    back_ids = slides.duplicate_slide_many(deck_id, back_template, len(sheets))

    # Drop the two template originals, then interleave so every front is
    # followed by a back: F1, B1, F2, B2, ...
    slides.delete_slides(deck_id, [front_template, back_template])
    slides.move_slides_to_indexes(
        deck_id,
        back_ids,
        [2 * index + 1 for index in range(len(back_ids))]
    )

    return deck_id


def main():
    if not os.getenv("API_KEY"):
        sys.exit("API_KEY is missing - add your Airtable token to Infrastructure/Airtable/.env.")
    if not BASE_ID or not DELEGATES_TABLE:
        sys.exit(
            "AirtableBaseID and AirtableTableName must be set in "
            "Infrastructure/Airtable/.env."
        )

    airtable = AirtableAPI()

    Display.display("Reading delegates from Airtable...")
    badges, problems = load_badges(airtable)

    for problem in problems:
        Display.display(f"SKIPPED: {problem}")

    if not badges:
        sys.exit("No delegate has both a country and a committee; nothing to print.")

    badges_by_school = group_by_school(badges)
    sheets = split_into_sheets(badges_by_school)
    report(badges_by_school, sheets)

    if "--dry-run" in sys.argv[1:]:
        Display.display("\nDry run - no deck was created.")
        return

    deck_id = build_deck(sheets)

    Display.display("")
    Display.display(f"Done. {sum(len(sheet) for sheet in sheets)} badges built.")
    Display.display(f"https://docs.google.com/presentation/d/{deck_id}/edit")


if __name__ == "__main__":
    main()
