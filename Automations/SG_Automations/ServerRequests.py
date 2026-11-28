import os
import requests
from urllib.parse import quote
from dotenv import load_dotenv

from SG_Automations.DataManager import SchoolDelegates
from Infrastructure import DisplayClass
load_dotenv()
Display = DisplayClass()

password = os.getenv("ServerPassword")

"""Pull every award out of the SCVMUN API.

Needs `requests`; everything else is the standard library.
"""

import json
import requests

BASE_URL = "https://scvmun.esuhsd.org" # deployment root, no trailing slash
ADMIN_CODE = os.getenv("ADMIN_CODE")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
TURNSTILE_TOKEN = os.getenv("TURNSTILE_TOKEN")  # optional, for Cloudflare Turnstile; can be None
TIMEOUT = 30 # In seconds

def _error_text(response):
    """The API's own {"message": ...} when it sent JSON, else a trimmed body."""
    try:
        body = json.loads(response.text)
    except ValueError:
        return (response.text or "<empty response>").strip()[:200]
    if isinstance(body, dict) and "message" in body:
        return body["message"]
    return (response.text or "").strip()[:200]

def login_as_admin(code=ADMIN_CODE, password=ADMIN_PASSWORD, turnstile_token=TURNSTILE_TOKEN, timeout=TIMEOUT, base_url=BASE_URL):
    if code is None:
        code = input("What is the admin hash (i.e. username)? This is set in the application's web interface.")
    if password is None:
        password = input("What is the admin password? This is set in the application's web interface.")
    base = base_url.rstrip("/")
    login = requests.post(
        f"{base}/api/auth/login",
        json={"hash": code, "password": password},
        headers={"X-Turnstile-Token": turnstile_token} if turnstile_token else None,
        timeout=timeout,
    )
    if login.status_code != 200:
        raise RuntimeError(f"Login failed ({login.status_code}): {_error_text(login)}")

    token = json.loads(login.text)["token"]
    return token

def get_awards(base_url=BASE_URL, timeout=TIMEOUT):
    """Log in as the admin and return every stored award.

    Returns a list of ``{"committee": str, "country": str, "award": str}``, already in the
    API's order: committees alphabetically, countries alphabetically within a committee.

    Raises RuntimeError with the server's message on a non-200, so a script can print it.
    """
    base = base_url.rstrip("/")

    # 1. The admin routes need a bearer token, so log in first.
    token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)
    # 2. Read the report.
    response = requests.get(
        f"{base}/api/admin/awards",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"GET /api/admin/awards failed ({response.status_code}): {_error_text(response)}"
        )

    # 3. Format: {committees: [{committee, awards: [{country, award}]}]}
    return json.loads(response.text)["committees"]

SCHOOLS_PATH = "/api/admin/schools"
HASHES_PATH = "/api/admin/hashes"
COMMITTEES_PATH = "/api/admin/committees"

def _admin_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def _post_admin(path, payload, token, base_url=BASE_URL, timeout=TIMEOUT):
    """POST a JSON payload to an admin route and return the decoded response."""
    response = requests.post(
        f"{base_url.rstrip('/')}{path}",
        json=payload,
        headers=_admin_headers(token),
        timeout=timeout,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"POST {path} failed ({response.status_code}): {_error_text(response)}")
    return response.json()

def _school_request_payload(SchoolInfo) -> dict:
    """Build the POST /api/admin/schools payload from the registration data."""
    fields = {
        "school_name": getattr(SchoolInfo, "schoolname", None),
        "school_address": getattr(SchoolInfo, "school_address", None),
        "city": getattr(SchoolInfo, "city", None),
        "state": getattr(SchoolInfo, "state", None),
        "zip_code": getattr(SchoolInfo, "zip_code", None),
        "advisor_name": getattr(SchoolInfo, "advisor_name", None),
        "advisor_phone": getattr(SchoolInfo, "advisor_phone", None),
        "advisor_email": getattr(SchoolInfo, "advisor_email", None),
        "head_delegate_name": getattr(SchoolInfo, "head_del_name", None),
        "head_delegate_email": getattr(SchoolInfo, "head_del_email", None),
        "head_delegate_phone": getattr(SchoolInfo, "head_del_phone", None),
    }
    missing = [name for name, value in fields.items() if value is None or str(value).strip() == ""]
    if missing:
        raise RuntimeError("Missing required school field(s): " + ", ".join(missing))

    payload = {name: str(value).strip() for name, value in fields.items()}
    payload["payment_status"] = getattr(SchoolInfo, "payment_status", None) or "unpaid"
    payload["invoiceURL"] = getattr(SchoolInfo, "invoice_url", None)
    return payload

def _final_assignments_payload(Delegates: SchoolDelegates) -> dict[str, list[str]]:
    """The server wants {display_label: [committee, country]}."""
    return {
        str(number): [Delegates.committee[number], Delegates.country[number]]
        for number in Delegates.number
    }

def _hashes_to_dict(payload):
    """Normalize a HashListResponse to {delegate_label: hash}, or return the raw payload."""
    if not isinstance(payload, dict):
        return payload

    entries = payload.get("hashes")
    if entries is None:
        return payload.get("data", payload)  # legacy shape
    if not isinstance(entries, list):
        return entries

    label_keys = ("delegate", "delegate_number", "name", "label", "key", "id", "account_id", "index")
    value_keys = ("hash", "access_code", "value")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        label = next((entry[key] for key in label_keys if entry.get(key) is not None), None)
        value = next((entry[key] for key in value_keys if entry.get(key) is not None), None)
        if label is not None and value is not None:
            result[str(label)] = value
    return result if result else entries

def create_school(SchoolInfo, token, base_url=BASE_URL, timeout=TIMEOUT) -> dict:
    """POST /api/admin/schools and return the SchoolEntry (includes advisor_hash)."""
    return _post_admin(SCHOOLS_PATH, _school_request_payload(SchoolInfo), token, base_url, timeout)

def create_delegate_hashes(SchoolInfo, Delegates: SchoolDelegates, token, base_url=BASE_URL, timeout=TIMEOUT) -> dict:
    """POST /api/admin/hashes for the delegates of an existing school."""
    payload = {
        "school_name": getattr(SchoolInfo, "schoolname", None),
        "finalAssignments": _final_assignments_payload(Delegates),
    }
    return _post_admin(HASHES_PATH, payload, token, base_url, timeout)

def create_school_and_request_hashes(SchoolInfo, Delegates: SchoolDelegates, base_url=BASE_URL, timeout=TIMEOUT):
    """
    Log in, create the school + advisor account, then mint hashes for its delegates.

    Returns {delegate_label: hash} on success, or None if the server call failed.
    """
    try:
        token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)

        SchoolInfo.payment_status = (
            Display.typing_with_pre_fill("Payment status:", "partially paid") or ""
        ).strip() or "partially paid"
        SchoolInfo.invoice_url = (
            Display.typing_with_pre_fill("Invoice URL (optional):", "") or ""
        ).strip() or None

        school = create_school(SchoolInfo, token, base_url, timeout)

        advisor_hash = school.get("advisor_hash")
        if advisor_hash:
            Display.display(f"School created. Advisor hash: {advisor_hash}")
        else:
            Display.display(
                f"School created (id={school.get('id')}, name={school.get('name')}). "
                "No advisor hash returned."
            )

        hashes_payload = create_delegate_hashes(SchoolInfo, Delegates, token, base_url, timeout)
        return _hashes_to_dict(hashes_payload)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        Display.display("Error: No server response. Check that the server is running and reachable.")
        return None
    except requests.exceptions.RequestException as e:
        Display.display(f"Error communicating with server: {e}")
        return None
    except RuntimeError as e:
        Display.display(f"Server error: {e}")
        return None

def request_hashes_for_new_delegates(SchoolInfo, Delegates: SchoolDelegates, base_url=BASE_URL, timeout=TIMEOUT):
    """
    Log in and mint hashes for delegates added to an existing school.

    Returns {delegate_label: hash} on success, or None if the server call failed.
    """
    try:
        token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)
        hashes_payload = create_delegate_hashes(SchoolInfo, Delegates, token, base_url, timeout)
        return _hashes_to_dict(hashes_payload)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        Display.display("Error: No server response. Check that the server is running and reachable.")
        return None
    except requests.exceptions.RequestException as e:
        Display.display(f"Error communicating with server: {e}")
        return None
    except RuntimeError as e:
        Display.display(f"Server error: {e}")
        return None

def delete_committee_delegate(committee_name, account_id, country, token=None, base_url=BASE_URL, timeout=TIMEOUT):
    """
    Remove one committee delegate. If `token` is not given, log in first.

    Calls DELETE /api/admin/committees/{committee_name}/delegates/{account_id}
    with confirm set to the delegate's current country. Returns the
    DelegateRemovedResponse dict, or None on failure.
    """
    if token is None:
        try:
            token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            Display.display("Error: No server response. Check that the server is running and reachable.")
            return None
        except requests.exceptions.RequestException as e:
            Display.display(f"Error communicating with server: {e}")
            return None
        except RuntimeError as e:
            Display.display(f"Server error: {e}")
            return None

    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        Display.display(f"Invalid account ID for {committee_name}/{country}: {account_id!r}")
        return None

    try:
        response = requests.delete(
            f"{base_url.rstrip('/')}{COMMITTEES_PATH}/{quote(committee_name, safe='')}/delegates/{account_id}",
            params={"confirm": country},
            headers=_admin_headers(token),
            timeout=timeout,
        )
        if response.status_code != 200:
            Display.display(f"Could not delete delegate ({response.status_code}): {_error_text(response)}")
            return None
        return response.json()
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        Display.display("Error: No server response. Check that the server is running and reachable.")
        return None
    except requests.exceptions.RequestException as e:
        Display.display(f"Error communicating with server: {e}")
        return None
def _parse_assignment(assignment):
    """'France (DISEC)' -> ('France', 'DISEC')."""
    if "(" not in assignment or not assignment.rstrip().endswith(")"):
        raise ValueError(f"Expected 'Country (Committee)', got {assignment!r}")
    country, committee = assignment.rsplit(" (", 1)
    return country.strip(), committee[:-1].strip()

def get_committee_detail(committee_name, token=None, base_url=BASE_URL, timeout=TIMEOUT) -> dict:
    """GET /api/admin/committees/{committee_name}; returns CommitteeDetailResponse."""
    if token is None:
        token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)
    response = requests.get(
        f"{base_url.rstrip('/')}{COMMITTEES_PATH}/{quote(committee_name, safe='')}",
        headers=_admin_headers(token),
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"GET /api/admin/committees/{committee_name} failed ({response.status_code}): {_error_text(response)}"
        )
    return response.json()

def drop_delegates_for_school(school_name, delegates_to_drop, base_url=BASE_URL, timeout=TIMEOUT):
    """
    Resolve each 'Country (Committee)' assignment to a server delegate and delete it.

    All committee lookups and delegate matches are resolved before the first DELETE,
    so a bad assignment cannot delete half the list. Returns the list of
    DelegateRemovedResponse dicts, or None if anything could not be resolved/deleted.
    """
    try:
        token = login_as_admin(ADMIN_CODE, ADMIN_PASSWORD, TURNSTILE_TOKEN, timeout, base_url)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        Display.display("Error: No server response. Check that the server is running and reachable.")
        return None
    except requests.exceptions.RequestException as e:
        Display.display(f"Error communicating with server: {e}")
        return None
    except RuntimeError as e:
        Display.display(f"Server error: {e}")
        return None

    committee_cache = {}
    used_account_ids = set()
    resolved = []

    for assignment in delegates_to_drop:
        try:
            country, committee = _parse_assignment(assignment)
        except ValueError as e:
            Display.display(str(e))
            return None

        if committee not in committee_cache:
            try:
                committee_cache[committee] = get_committee_detail(committee, token, base_url, timeout)
            except (RuntimeError, requests.exceptions.RequestException) as e:
                Display.display(f"Could not load committee '{committee}': {e}")
                return None

        entries = committee_cache[committee].get("delegates") or []
        match = next(
            (
                entry for entry in entries
                if entry.get("account_id") is not None
                and entry["account_id"] not in used_account_ids
                and str(entry.get("school_name", "")).strip().lower() == school_name.strip().lower()
                and str(entry.get("country", "")).strip().lower() == country.strip().lower()
            ),
            None,
        )
        if match is None:
            Display.display(f"No server delegate found for '{assignment}' at '{school_name}'.")
            return None

        used_account_ids.add(match["account_id"])
        resolved.append((committee, country, match["account_id"]))

    removed = []
    for committee, country, account_id in resolved:
        result = delete_committee_delegate(committee, account_id, country, token, base_url, timeout)
        if result is None:
            return None
        removed.append(result)
    return removed
