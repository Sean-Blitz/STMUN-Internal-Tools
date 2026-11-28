"""
Exercise Awards.generate_all_awards_by_committee with a native Python awards object.

The function still reads the real Overview sheet (committee names + double status).
By default this is a DRY RUN: slide duplication/placeholder writes are recorded, not
sent to Google Slides. Pass --live to modify the real AWARD_SLIDE_ID presentation.

Usage:
    python test_awards_generation.py            # safe dry run
    python test_awards_generation.py --live     # actually generate the deck
"""

import argparse
import sys
from pathlib import Path

AUTOMATIONS_DIR = Path(__file__).resolve().parent.parent
if str(AUTOMATIONS_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATIONS_DIR))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from SG_Automations import Awards

# (name in the Overview sheet, full name to print on the award slide)
COMMITTEES = [
    ("Security Council", "Security Council"),
    ("Historical Crisis", "Historical Crisis"),
    ("ICJ", "International Court of Justice"),
    ("NATO", "North Atlantic Treaty Alliance"),
    ("UNHRC", "United Nations Human Rights Council"),
    ("Ad Hoc Local", "Ad Hoc Local"),
    ("World Bank", "World Bank"),
    ("COPUOS", "Committee on the Peaceful Uses of Outer Space"),
    ("DISEC", "Disarmament and International Security Committee"),
    ("WHO", "World Health Organization"),
    ("UNEP", "United Nations Environment Programme"),
    ("SOCHUM", "Social, Humanitarian and Cultural Committee"),
    ("UNESCO", "United Nations Educational, Scientific and Cultural Organization"),
    ("UNDP", "United Nations Development Programme"),
    ("CSW", "Commission on the Status of Women"),
]

# A few plausible delegates per committee.
COUNTRIES = {
    "Security Council": ["United States", "China", "France"],
    "Historical Crisis": ["Germany", "Soviet Union", "United Kingdom"],
    "ICJ": ["Brazil", "India", "Norway"],
    "NATO": ["United States", "Germany", "Poland"],
    "UNHRC": ["South Africa", "Canada", "Japan"],
    "Ad Hoc Local": ["Kenya", "Mexico", "Indonesia"],
    "World Bank": ["United States", "China", "Nigeria"],
    "COPUOS": ["India", "France", "Brazil"],
    "DISEC": ["Germany", "Egypt", "Australia"],
    "WHO": ["Switzerland", "India", "Brazil"],
    "UNEP": ["Norway", "Kenya", "Costa Rica"],
    "SOCHUM": ["France", "Philippines", "Ghana"],
    "UNESCO": ["Italy", "Japan", "Mexico"],
    "UNDP": ["Denmark", "Bangladesh", "Rwanda"],
    "CSW": ["Sweden", "Chile", "Jordan"],
}


def build_fake_awards():
    """Every committee gets 2 awards; every third committee gets a third award."""
    fake = []
    for index, (sheet_name, _) in enumerate(COMMITTEES):
        countries = COUNTRIES[sheet_name]
        awards = [
            {"country": countries[0], "award": "Best Delegate"},
            {"country": countries[1], "award": "Outstanding Delegate"},
        ]
        if index % 3 == 0:
            awards.append({"country": countries[2], "award": "Honorable Mention"})
        fake.append({"committee": sheet_name, "awards": awards})
    return fake


class RecordingSlides:
    """Stands in for Awards.Slides during a dry run."""

    def __init__(self):
        self.batch = {}
        self.first_slide = "dry-run-first-slide"

    def get_first_slide_id(self, presentation_id):
        return self.first_slide

    def duplicate_slide_many(self, presentation_id, slide_object_id, count):
        return [f"dry-run-slide-{i}" for i in range(1, count + 1)]

    def batch_update_slides_text(self, presentation_id, placeholder_text, slide_updates):
        self.batch[placeholder_text] = dict(slide_updates)


def non_interactive_committee_names():
    """Answer the function's 'real committee name' prompt from COMMITTEES."""
    def answer(prompt):
        for sheet_name, full_name in COMMITTEES:
            if f"Current Committee Name: {sheet_name}." in prompt:
                return full_name
        raise ValueError(f"Unexpected committee prompt: {prompt}")

    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Actually duplicate/fill slides in AWARD_SLIDE_ID.")
    args = parser.parse_args()

    fake_awards = build_fake_awards()

    # Show how the fake committees line up with the real Overview sheet.
    names = Awards.SheetsAPI.get_column_data_until_empty(
        Awards.REGISTRATION_SHEET_ID, "Overview", "A", 2
    )
    status_values = Awards.SheetsAPI.read_cells(
        Awards.REGISTRATION_SHEET_ID, [f"Overview!E{i+2}" for i in range(len(names))]
    )
    double_status = {
        Awards._normalize(name): Awards._as_bool(value)
        for name, value in zip(names, status_values)
    }

    missing = [name for name, _ in COMMITTEES if Awards._normalize(name) not in double_status]
    print(f"Real Overview committees: {len(names)}")
    print(f"Fake committees missing from Overview: {missing or 'none'}")
    print("Double-delegation committees from the sheet:",
          [name for name, _ in COMMITTEES if double_status.get(Awards._normalize(name), False)])

    award_total = sum(len(entry["awards"]) for entry in fake_awards)
    slide_total = sum(
        len(entry["awards"]) * (2 if double_status.get(Awards._normalize(entry["committee"]), False) else 1)
        for entry in fake_awards
    )
    print(f"Fake awards: {award_total}; expected slides after doubling: {slide_total}")

    Awards.Display.take_text_input = non_interactive_committee_names()

    if args.live:
        Awards.generate_all_awards_by_committee(fake_awards)
        print("Live generation complete:")
        print(f"https://docs.google.com/presentation/d/{Awards.AWARD_SLIDE_ID}/edit")
        return

    recorder = RecordingSlides()
    Awards.Slides = recorder
    Awards.generate_all_awards_by_committee(fake_awards)

    committee_map = recorder.batch.get("{{COMMITTEE_NAME}}", {})
    award_map = recorder.batch.get("{{AWARD_NAME}}", {})
    country_map = recorder.batch.get("{{COUNTRY_NAME}}", {})
    print(f"Dry run: would fill {len(committee_map)} slides.")
    for slide_id in list(committee_map)[:5]:
        print(f"  {slide_id}: {committee_map[slide_id]} | {award_map.get(slide_id)} | {country_map.get(slide_id)}")
    print("Dry run complete. Re-run with --live to write to the real deck.")


if __name__ == "__main__":
    main()
