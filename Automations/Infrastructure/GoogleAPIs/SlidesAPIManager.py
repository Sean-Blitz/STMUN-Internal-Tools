from .GoogleAPIsManager import GoogleAPIs
from googleapiclient.discovery import build
from ..utilities import retry_on_http_error
from ..Display.DisplayManager import DisplayClass
from typing import Any, Dict

Display = DisplayClass()

class SlideAPI(GoogleAPIs):
    def __init__(self, SCOPES = None, CREDENTIALS_FILE = None, TOKEN_FILE = None):
        if SCOPES is None:
            super().__init__(CREDENTIALS_FILE=CREDENTIALS_FILE, TOKEN_FILE=TOKEN_FILE)
            # As defined in the parent class, if Credentials or Token file is none, it will default to the standard locations.
        elif SCOPES is not None:
            super().__init__(SCOPES=SCOPES, CREDENTIALS_FILE=CREDENTIALS_FILE, TOKEN_FILE=TOKEN_FILE)
        else:
            raise ValueError("SCOPES must be a list of scopes or None.")
        creds = self.authenticate()
        self.service = build('slides', 'v1', credentials=creds)
        # Every method calls self.presentations(), so expose the bound service method
        # rather than the service resource itself.
        self.presentations = self.service.presentations

    @retry_on_http_error()
    def duplicate_slide(self, presentation_id, slide_object_id):
        """
        Duplicates a slide in a Google Slides presentation and returns the new slide's object ID.
        """

        body = {
            "requests": [
                {
                    "duplicateObject": {
                        "objectId": slide_object_id
                    }
                }
            ]
        }

        response = self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=body
        ).execute()

        # The API returns a list of replies; the first one contains the new object ID
        new_slide_id = response["replies"][0]["duplicateObject"]["objectId"]
        return new_slide_id

    @retry_on_http_error()
    def duplicate_slide_many(self, presentation_id, slide_object_id, count):
        """
        Duplicates one slide `count` times in a single batchUpdate.

        One call per duplicate hits the Slides write quota almost immediately on
        a full conference deck, so the copies are requested together.

        Returns:
            list: New slide object IDs in creation order (replies come back in
                the same order as the requests)
        """
        if count <= 0:
            return []

        body = {
            "requests": [
                {"duplicateObject": {"objectId": slide_object_id}}
                for _ in range(count)
            ]
        }

        response = self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=body
        ).execute()

        return [
            reply["duplicateObject"]["objectId"]
            for reply in response.get("replies", [])
        ]

    @retry_on_http_error()
    def replace_placeholders(self, presentation_id, value_map):
        """
        Replace placeholders in a Google Slides presentation.

        Args:
            presentation_id: The ID of the presentation
            value_map: Dict of {placeholder: replacement_value}
        """

        requests = []

        for placeholder, new_value in value_map.items():
            requests.append({
                "replaceAllText": {
                    "containsText": {
                        "text": placeholder,
                        "matchCase": True
                    },
                    "replaceText": str(new_value)
                }
            })

        body = {"requests": requests}

        response = self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=body
        ).execute()

        return response

    @retry_on_http_error()
    def replace_two_placeholders_on_slide(self,presentation_id,slide_id,old_placeholder_1,new_placeholder_1,old_placeholder_2,new_placeholder_2):
        """
        Replaces two different placeholders on a specific slide with new placeholder names.
        Only affects the slide whose ID is passed in.
        """

        body = {
            "requests": [
                {
                    "replaceAllText": {
                        "containsText": {
                            "text": old_placeholder_1,
                            "matchCase": True
                        },
                        "replaceText": new_placeholder_1,
                        "pageObjectIds": [slide_id]
                    }
                },
                {
                    "replaceAllText": {
                        "containsText": {
                            "text": old_placeholder_2,
                            "matchCase": True
                        },
                        "replaceText": new_placeholder_2,
                        "pageObjectIds": [slide_id]
                    }
                }
            ]
        }

        response = self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=body
        ).execute()

        # Return how many replacements were made for each placeholder
        reply1 = response.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        reply2 = response.get("replies", [{}])[1].get("replaceAllText", {}).get("occurrencesChanged", 0)

        return reply1, reply2

    @retry_on_http_error()
    def get_first_slide_id(self, presentation_id):
        """
        Returns the object ID of the first slide in a Google Slides presentation.
        """

        presentation = self.presentations().get(
            presentationId=presentation_id
        ).execute()

        first_slide = presentation["slides"][0]
        return first_slide["objectId"]

    @retry_on_http_error()
    def move_slides_to_indexes(self, presentation_id, slide_ids, target_indexes):
        """
        Moves each slide to its target index in a single batchUpdate.

        Requests inside one batchUpdate are applied in order, so ascending
        targets behave exactly like sequential calls while costing one request
        instead of one per slide.
        """
        if len(slide_ids) != len(target_indexes):
            raise ValueError("slide_ids and target_indexes must match length.")
        if not slide_ids:
            return

        moves = sorted(zip(slide_ids, target_indexes), key=lambda move: move[1])

        requests = [
            {
                "updateSlidesPosition": {
                    "slideObjectIds": [slide_id],
                    "insertionIndex": target_index
                }
            }
            for slide_id, target_index in moves
        ]

        self.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests}
        ).execute()

    @retry_on_http_error()
    def get_slide_id_by_index(self, presentation_id, index):
        """
        Returns the objectId of the slide at the given index.

        Args:
            self: Authenticated Google Slides API service.
            presentation_id (str): ID of the presentation.
            index (int): 0-based slide index.

        Returns:
            str: The slide's objectId.
        """

        if not isinstance(index, int) or index < 0:
            raise ValueError("Index must be a non-negative integer.")

        presentation = self.presentations().get(
            presentationId=presentation_id
        ).execute()

        slides = presentation.get("slides", [])

        if index >= len(slides):
            raise IndexError(
                f"Index {index} out of range. Presentation has {len(slides)} slides."
            )

        return slides[index]["objectId"]

    @retry_on_http_error()
    def replace_placeholders_on_slide(
        self,
        presentation_id,
        slide_id,
        value_map
    ):
        """
        Replaces placeholders on a single slide only.

        Args:
            self: Authenticated Google Slides API service
            presentation_id (str): ID of the presentation
            slide_id (str): Object ID of the slide to modify
            value_map (dict): {placeholder_text: replacement_text}

        Example value_map:
            {
                "{COUNTRY_1}": "France",
                "{COUNTRY_2}": "Germany"
            }
        """

        if not value_map:
            return

        requests = []

        for placeholder, new_value in value_map.items():
            requests.append({
                "replaceAllText": {
                    "containsText": {
                        "text": placeholder,
                        "matchCase": True
                    },
                    "replaceText": new_value,
                    "pageObjectIds": [slide_id]  # restrict to this slide only
                }
            })

        body = {"requests": requests}

        self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=body
        ).execute()

    def batch_update_slides_text(
        self,
        presentation_id: str,
        placeholder_text: str,
        slide_updates: Dict[str, str],
        match_case: bool = True
        ) -> Dict[str, Any]:
        """
        Replaces a uniform placeholder string with unique text across multiple slides
        in a single Google Slides API batchUpdate call.

        Args:
            slides_service: Authenticated Google Slides API service resource 
                            (e.g., build('slides', 'v1', credentials=creds)).
            presentation_id: The ID of the Google Slides presentation (from its URL).
            placeholder_text: The identical placeholder string present on the slides 
                            (e.g., "{{TITLE}}").
            slide_updates: A dictionary mapping each slide's pageObjectId (str) to 
                        the replacement text (str) for that specific slide.
            match_case: Whether the placeholder search should be case-sensitive. 
                        Defaults to True.

        Returns:
            The JSON response dictionary from the Google Slides API batchUpdate call.
        """
        requests = [
            {
                "replaceAllText": {
                    "containsText": {
                        "text": placeholder_text,
                        "matchCase": match_case
                    },
                    "replaceText": new_text,
                    "pageObjectIds": [slide_id]
                }
            }
            for slide_id, new_text in slide_updates.items()
        ]

        if not requests:
            return {"replies": []}

        return (
            self.presentations()
            .batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests}
            )
            .execute()
        )

    @retry_on_http_error()
    def get_slide_count(self, presentation_id):
        """
        Returns the number of slides in a Google Slides presentation.

        Args:
            self: Authenticated Google Slides API service
            presentation_id (str): ID of the presentation

        Returns:
            int: Number of slides
        """

        presentation = self.presentations().get(
            presentationId=presentation_id,
            fields="slides(objectId)"  # only fetch slide IDs (faster)
        ).execute()

        slides = presentation.get("slides", [])
        return len(slides)

    @retry_on_http_error()
    def delete_slide(self, presentation_id, slide_id):
        """
        Deletes a slide from a presentation using its object ID.

        Args:
            self: Authenticated Google Slides API service
            presentation_id (str): ID of the presentation
            slide_id (str): Object ID of the slide to delete
        """

        request = {
            "requests": [
                {
                    "deleteObject": {
                        "objectId": slide_id
                    }
                }
            ]
        }

        self.presentations().batchUpdate(
            presentationId=presentation_id,
            body=request
        ).execute()

    @retry_on_http_error()
    def delete_slides(self, presentation_id, slide_ids):
        """
        Deletes several slides in a single batchUpdate.

        Args:
            self: Authenticated Google Slides API service
            presentation_id (str): ID of the presentation
            slide_ids (list): Object IDs of the slides to remove
        """
        slide_ids = [slide_id for slide_id in slide_ids if slide_id]
        if not slide_ids:
            return

        self.presentations().batchUpdate(
            presentationId=presentation_id,
            body={
                "requests": [
                    {"deleteObject": {"objectId": slide_id}}
                    for slide_id in slide_ids
                ]
            }
        ).execute()